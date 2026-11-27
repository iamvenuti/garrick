"""Remote access (preview) in Settings: each state, drawn (#695, #697, #698, #696).

    cd tests && python3 -m unittest test_remote_settings

The section is drawn from what `view_settings.py` reads through the extra's `state.py`; `status.py` only draws it. Every state is rendered:
not installed, off, on, paused, a roaming computer, a pairing code waiting, grants with their reach. Each says Preview, and none shows a
path, a key or a command outside its Details fold.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extras" / "remote" / "tests"))

from remote_fixture import EXTRA, REPO, mod  # noqa: E402
from test_settings_ui import SettingsCase, sh  # noqa: E402
from test_status import status  # noqa: E402

TOOLS = REPO / "template" / "System" / "tools"
sys.path.insert(0, str(TOOLS))
import view_settings  # noqa: E402


class Case(SettingsCase):
    def setUp(self):
        super().setUp()
        base = Path(self._tmp.name).resolve()
        os.environ["GARRICK_REMOTE_HOME"] = str(base / "remote-state")
        self.addCleanup(os.environ.pop, "GARRICK_REMOTE_HOME", None)
        for name in list(sys.modules):
            if name.startswith("garrick_remote_") or name == "garrick_settings_remote_state":
                del sys.modules[name]
        self.state, self.store = mod("state"), mod("store")
        # zones for the fixture's context, with one open and one walled
        (self.root / "System" / "context.md").write_text(
            "# Context\n\n## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n| Work | Client work | yes |\n| Personal | Home | no |\n", encoding="utf-8")

    def install(self):
        (self.root / "System" / "remote").symlink_to(EXTRA)

    def draw(self):
        data = status.settings_data(self.root)
        return status.remote_settings(self.root, data)

    def turn_on(self):
        self.state.set_address("https://home.example.test", "own")
        self.state.set_status("on")


class States(Case):
    def test_not_installed_says_so_and_offers_one_step(self):
        out = self.draw()
        self.assertIn('id="remote-settings"', out)
        self.assertIn('data-state="missing"', out)
        self.assertIn("Not installed", out)
        self.assertIn("data-request=", out)
        self.assertIn("extras/remote", out)
        self.assertIn("Updating Garrick then keeps it current", out)
        self.assertIn("Preview", out)

    def test_off(self):
        self.install()
        out = self.draw()
        self.assertIn('data-state="off"', out)
        self.assertIn(">Off<", out)
        self.assertIn("Preview", out)
        self.assertIn('data-raction="enable"', out)
        self.assertIn("Through a relay", out)
        self.assertIn("Through an address I already have", out)
        self.assertIn("No assistant is connected yet", out)

    def test_on_shows_the_address_the_buttons_and_the_steps(self):
        self.install()
        self.turn_on()
        out = self.draw()
        self.assertIn('data-state="on"', out)
        self.assertIn("https://home.example.test", out)
        for action in ("pause", "off", "pair"):
            self.assertIn('data-raction="%s"' % action, out)
        self.assertEqual(re.findall(r'data-step="(\w+)" data-done="(\w+)"', out),
                         [("on", "true"), ("software", "false"), ("address", "true"), ("service", "false"), ("assistant", "false")])

    def test_paused_offers_resume(self):
        self.install()
        self.turn_on()
        self.state.set_status("paused")
        out = self.draw()
        self.assertIn('data-state="paused"', out)
        self.assertIn(">Paused<", out)
        self.assertIn('data-raction="resume"', out)

    def test_a_roaming_computer_is_told_why_and_gets_no_switch(self):
        self.install()
        self.role("roaming")
        out = self.draw()
        self.assertIn('data-state="refused"', out)
        self.assertIn("roaming", out)
        self.assertNotIn("data-raction", out)

    def test_a_pairing_code_waiting_is_said_without_the_code(self):
        self.install()
        self.turn_on()
        code, _ = self.store.make_pairing_code()
        out = self.draw()
        self.assertIn("A code is waiting", out)
        self.assertNotIn(code, out)

    def test_the_waiting_sign_in_requests_are_listed_with_their_name_and_start(self):
        self.install()
        self.turn_on()
        self.store.put_pending({"client": "c1", "name": "Maple <b>phone</b>", "challenge": "CHALLENGEX", "state": "STATEX", "redirect": "http://r.example"})
        self.store.put_pending({"client": "c2", "name": "Cedar tablet"})
        out = self.draw()
        block = re.search(r'<div class="rrequests" id="remote-requests">.*?</ul></div>', out, re.S).group(0)
        self.assertEqual(2, block.count('class="rreq"'))
        self.assertIn("Maple &lt;b&gt;phone&lt;/b&gt;", block)
        self.assertNotIn("<b>phone</b>", block)
        self.assertIn("Cedar tablet", block)
        self.assertEqual(2, block.count("Started less than a minute ago."))
        self.assertEqual(2, block.count('type="radio"'))                               # with several waiting, one is picked
        self.assertIn("Pick the sign-in you started", block)
        for secret in ("CHALLENGEX", "STATEX", "r.example"):
            self.assertNotIn(secret, out)

    def test_with_one_request_waiting_there_is_nothing_to_pick(self):
        self.install()
        self.turn_on()
        self.store.put_pending({"client": "c1", "name": "Maple phone"})
        block = re.search(r'<div class="rrequests" id="remote-requests">.*?</ul></div>', self.draw(), re.S).group(0)
        self.assertEqual(1, block.count('class="rreq"'))
        self.assertNotIn('type="radio"', block)
        self.assertIn("Choose Show a code for this sign-in.", block)

    def test_with_none_waiting_the_page_says_so_in_one_sentence(self):
        self.install()
        self.turn_on()
        out = self.draw()
        self.assertIn('id="remote-norequests">No sign-in is waiting. Start one in your assistant, then choose Show a code.', out)
        self.assertNotIn('class="rreq"', out)

    def test_a_failed_reply_is_drawn_by_the_pages_failure_row_never_as_raw_text(self):
        js = (EXTRA.parent / "status" / "settings_remote.py").read_text()
        tell = js.split("function tell(", 1)[1].split("\nfunction send(", 1)[0]
        self.assertIn("GarrickFail(said,code||'remote',String(t||''))", tell)           # the sentence, the tool's text under Details
        self.assertIn("GarrickFailClear(said)", tell)                              # a later success takes the drawing away
        self.assertLess(tell.index("GarrickFail(said"), tell.index("said.textContent=String(t||'')}"))
        self.assertIn("tell(out.say,!out.ok,", js)
        built = (EXTRA.parent / "status" / "status.py").read_text()
        self.assertIn("window.GarrickFail=function", built)                         # the page defines it, with a default row for an unknown code

    def test_a_reply_nobody_could_settle_is_never_drawn_as_not_changed(self):
        js = (EXTRA.parent / "status" / "settings_remote.py").read_text()
        self.assertIn("GarrickFail(said,code||'remote'", js)
        self.assertIn("var none=!out", js)
        self.assertIn("tell(out.say,!out.ok,none?'lost':odd?'unknown':'remote')", js)        # no reply: the lost row, Refresh
        self.assertIn("/^(unknown|lost|crashed)$/.test(String((out.plain&&out.plain.code)||out.outcome||''))", js)
        for code in ("lost", "unknown"):
            self.assertIn('("%s", ' % code, (EXTRA.parent / "status" / "page_action.py").read_text())      # the rows are the page's own

    def test_the_show_a_code_button_sends_the_picked_request(self):
        out = (EXTRA.parent / "status" / "settings_remote.py").read_text()
        self.assertIn("input[name=remote-request]:checked", out)
        self.assertIn("q.request=pick.value", out)
        self.assertIn("q.request=one[0].dataset.request", out)

    def test_a_pairing_code_waiting_names_the_request_it_is_for_by_its_id_only(self):
        self.install()
        self.turn_on()
        self.store.put_pending({"client": "c1", "name": "Maple phone"})
        self.store.put_pending({"client": "c2", "name": "Cedar tablet"})
        first, second = self.store.waiting_requests()
        code, _ = self.store.make_pairing_code(request=second["id"])
        out = self.draw()
        self.assertRegex(out, r'<input type="radio" name="remote-request" value="%s" checked>' % second["id"])
        self.assertNotIn(code, out)

    def test_grants_are_listed_with_their_reach_and_a_revoke(self):
        self.install()
        self.turn_on()
        gid = self.store.create_grant("c1", "Maple phone", ["read", "write"])
        self.store.set_zone(gid, "Work", True, False, marker=mod("context").zone_marker(self.root, "Work"))
        out = self.draw()
        self.assertIn("Maple phone", out)
        self.assertIn('data-revoke="%s"' % gid, out)
        self.assertIn("can read and write", out)
        work = re.search(r'<li class="rreach walled" data-zone="Work".*?</li>', out, re.S).group(0)
        self.assertRegex(work, r'data-rr="read" checked')
        self.assertNotRegex(work, r'data-rr="write" checked')
        self.assertIn("On since", work)
        self.assertRegex(out, r'<li class="rreach open" data-zone="Personal"')

    def test_the_notice_is_in_the_page_for_each_walled_zone_before_it_can_be_turned_on(self):
        self.install()
        self.turn_on()
        self.store.create_grant("c1", "Maple phone", ["read"])
        out = self.draw()
        notice = (EXTRA / "notice.md").read_text().strip().replace("{zone}", "Work")
        work = re.search(r'<li class="rreach walled" data-zone="Work".*?</li>', out, re.S).group(0)
        self.assertIn('<p class="hint rnotice" hidden>', work)
        self.assertIn(notice.replace("&", "&amp;").replace("'", "&#x27;"), work)
        self.assertIn("data-rconfirm", out)
        self.assertRegex(work, r'data-rr="write"[^>]* disabled')                    # a read-only grant cannot be given writes

    def test_nothing_secret_is_drawn(self):
        self.install()
        self.turn_on()
        gid = self.store.create_grant("c1", "Maple phone", ["read"])
        pair = self.store.issue(gid, "c1", ["read"], "https://home.example.test/mcp")
        out = self.draw()
        for secret in (pair["access"], pair["refresh"], self.store.sha(pair["access"])):
            self.assertNotIn(secret, out)

    def test_every_state_says_preview_and_has_plain_words(self):
        pages = []
        pages.append(self.draw())                                                   # not installed
        self.install()
        pages.append(self.draw())                                                   # off
        self.turn_on()
        pages.append(self.draw())                                                   # on
        self.state.set_status("paused")
        pages.append(self.draw())                                                   # paused
        self.role("roaming")
        pages.append(self.draw())                                                   # roaming
        for out in pages:
            self.assertIn("Preview", out)
            text = re.sub(r"<details.*?</details>", "", out, flags=re.S)             # Details is where a technical word may live
            text = re.sub(r"<[^>]+>", " ", text)
            for bad in ("/Users", "~/", ".py", "launchctl", "settings.json", "127.0.0.1", "Traceback", "stdout", "--"):
                self.assertNotIn(bad, text)

    def test_reading_writes_nothing(self):
        self.install()
        status.settings_data(self.root)
        self.assertFalse(Path(os.environ["GARRICK_REMOTE_HOME"]).exists())

    def test_the_section_is_in_settings_after_walls_and_listed_in_the_nav(self):
        self.install()
        full = self.full()
        self.assertIn('id="remote-settings"', full)
        self.assertLess(full.index('id="walls-settings"'), full.index('id="remote-settings"'))
        self.assertLess(full.index('id="remote-settings"'), full.index('id="look-settings"'))
        self.assertRegex(full, r'data-setgo="remote-settings">Remote access<')

    def test_a_garrick_without_the_extra_draws_the_section_as_not_installed_and_nothing_breaks(self):
        full = self.full()
        self.assertIn('data-state="missing"', full)

    def test_the_script_sends_only_the_remote_verb_and_the_reach_choices_are_separate(self):
        js = status.SETREMOTE_JS
        self.assertIn("verb:'remote'", js)
        for action in ("enable", "pause", "resume", "off", "pair", "zone", "revoke"):
            self.assertIn("'%s'" % action, js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("XMLHttpRequest", js)


class Document(Case):
    def test_the_document_holds_the_remote_part_and_only_when_asked(self):
        self.install()
        doc = view_settings.read(self.root, REPO / "extras" / "status", only=("remote",))
        self.assertEqual(set(doc), {"api", "remote"})
        self.assertTrue(doc["remote"]["installed"])
        self.assertEqual(doc["remote"]["label"], "Preview")
        self.assertNotIn("remote", view_settings.read(self.root, REPO / "extras" / "status", only=("desk",)))
        json.dumps(view_settings.read(self.root, REPO / "extras" / "status"))

    def test_a_reader_that_fails_leaves_the_part_not_installed(self):
        self.install()
        (self.root / "System" / "remote").unlink()
        (self.root / "System" / "remote").mkdir()
        (self.root / "System" / "remote" / "state.py").write_text("raise RuntimeError('x')")
        self.assertFalse(view_settings.remote(self.root)["installed"])


if __name__ == "__main__":
    unittest.main()
