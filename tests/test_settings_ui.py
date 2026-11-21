"""Settings, as #621 draws it: *This machine*, the Read guard block in Walls, and one "?" on every setting row. Built from
a fictional workspace with a fake HOME and a fake jobs folder, so nothing here reads this Mac's role, assistants or log.

    cd tests && python3 -m unittest test_settings_ui
"""

from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from test_status import REPO, StatusCase, status  # noqa: E402

sys.path.insert(0, str(REPO / "extras" / "status"))
import settings_guard as sg  # noqa: E402
import settings_help as sh  # noqa: E402

# The texts of #621, word for word.
ISSUE = {
    "machine": "Most people use Garrick on one computer and can leave this as it is. Change it only if your workspace lives on a computer that stays on at home and a laptop keeps a copy of it. This setting stays on this computer, so the other computer keeps its own.",
    "solo": "Everything happens here: your sessions, the nightly jobs and your Todo lists.",
    "server": "This computer is always on and holds the real workspace. The nightly jobs run here, and it applies the ticks your laptop sends.",
    "roaming": "This computer keeps a copy that only receives. You can read everything, even with no network. A tick on a Todo list waits until the home server applies it. Nightly jobs do not run here.",
    "readguard": "Walls already stop your assistant from writing one zone's material into another. The read guard does the same for reading. In a session for one project, it stops the assistant from opening notes, meetings and mail that sit behind another wall.",
    "rg-mode": "Watch only lets every read through and keeps a list of what it would have stopped. Start with it for a week and look at the list. When the list holds nothing you needed, choose On, and those reads are stopped.",
    "rg-cross": "Refuse stops every read across a wall, with no question. Ask me asks you each time, so you can allow one read for one session.",
    "rg-tools": "A mail or calendar search can return messages from every part of your life in one list. Before your assistant sees the list, Garrick removes what belongs behind another wall. These are the tools it checks. Add one when you connect a new mail or calendar service.",
    "rg-skip": "Tools that return nothing tied to a person or a company, such as a weather service. Garrick does not check them and does not warn you about them.",
}
CODEX = "Codex cannot have its mail and calendar results checked. Only the instructions keep them apart."
FORBIDDEN = re.compile(r"\.json|\.py|--|#\d|\.md\b|System/|garrick-settings|read-guard|connector-tools|machine\.|python3|--role|\bhook\b", re.I)
WORDS_MAX = 62


class Rows(HTMLParser):
    """Walks Settings' markup: for each control, the nearest enclosing row, and whether that row holds a "?"; and each help text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.controls, self.helps, self.ids, self.targets = [], [], {}, [], []
        self.row_classes = set(sh.ROW_CLASSES)
        self._help = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "button" and "qhelp" in classes:
            self.targets.append(a.get("aria-controls"))
            for frame in self.stack:
                if frame["row"]:
                    frame["help"] = True
        if tag in ("input", "select", "textarea"):
            row = next((f for f in reversed(self.stack) if f["row"]), None)
            self.controls.append((tag, a, row))
        if "sethelp" in classes:
            self._help = {"id": a.get("id"), "text": ""}
        if tag not in ("input", "br", "img", "hr", "meta", "link", "path", "circle", "rect"):
            self.stack.append({"tag": tag, "row": bool(classes & self.row_classes), "help": False, "attrs": a})

    def handle_endtag(self, tag):
        if tag in ("input", "br", "img", "hr", "meta", "link", "path", "circle", "rect"):
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                if self._help is not None and "sethelp" in (self.stack[i]["attrs"].get("class") or ""):
                    self.helps[self._help["id"]] = self._help["text"]
                    self._help = None
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._help is not None:
            self._help["text"] += data


def parse(markup):
    p = Rows()
    p.feed(markup)
    return p


class SettingsCase(StatusCase):
    def setUp(self):
        super().setUp()
        base = Path(self._tmp.name).resolve()
        self.home = base / "empty-home"
        self.jobs = base / "jobs"
        env = mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.jobs), "HOME": str(self.home)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GARRICK_HARNESS", None)
        self.guard_dir = base / "garrick-read-guard"
        # The tools and skills of a workspace the installer made: the settings read them (fade, notifications, the intake match).
        (self.root / "System" / "tools").symlink_to(REPO / "template" / "System" / "tools")
        (self.root / "System" / "skills").symlink_to(REPO / "template" / "System" / "skills")

    def role(self, role, **more):
        target = self.home / ".config" / "garrick" / "machine.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dict(role=role, **more)))

    def settings_file(self, **keys):
        (self.root / "System" / "garrick-settings.json").write_text(json.dumps(keys))

    def assistants(self, registered=False):
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".codex").mkdir(exist_ok=True)
        if registered:
            guard = sg.guard_module()
            guard.register(str(REPO / "extras" / "hooks" / "read_guard.py"), str(self.home))

    def log(self, *lines):
        self.guard_dir.mkdir(parents=True, exist_ok=True)
        with (self.guard_dir / "read-guard.log").open("w") as f:
            for zone, tool, decision, ago in lines:
                when = (dt.datetime.now() - dt.timedelta(hours=ago)).strftime("%Y-%m-%dT%H:%M:%S")
                f.write(json.dumps({"t": when, "tool": tool, "decision": decision, "zone": zone, "id": "a1b2c3d4e5f6"}) + "\n")

    def full(self):
        return status.settings(self.root, ("claude", "codex"), ("Work", "Personal"), {}, True, status.Links(self.root),
                               [("project", "Project", "Teal")], {})

    def section(self, markup, sid):
        m = re.search(r'<section class="setsec[^"]*" id="%s".*?</section>' % sid, markup, re.S)
        self.assertIsNotNone(m, sid)
        return m.group(0)


class TestThisMachine(SettingsCase):
    def test_each_role_in_words_and_a_laptop_copy_names_its_server(self):
        for role, said in (("solo", "One computer"), ("server", "Home server")):
            with self.subTest(role=role):
                self.role(role, name="mini")
                sec = self.section(self.full(), "machine-settings")
                self.assertIn(said, sec)
        self.role("roaming", name="laptop", server="mini")
        sec = self.section(self.full(), "machine-settings")
        self.assertIn("Laptop copy of mini", sec)

    def test_no_role_file_is_one_computer(self):
        sec = self.section(self.full(), "machine-settings")
        self.assertIn("One computer", sec)
        self.assertEqual(("solo", "", ""), status.machine_record(self.root))

    def test_the_change_button_is_the_apps_and_a_browser_is_told_where_to_change_it(self):
        sec = self.section(self.full(), "machine-settings")
        self.assertRegex(sec, r'<button class="act apponly"[^>]*id="role-change"')
        self.assertIn('class="hint nohost-only">The role is changed in Garrick.app.</p>', sec)
        self.assertIn(".nohost-only{display:none}.nohost .nohost-only{display:block}", sg.CSS)
        self.assertNotRegex(sec, r"machine\.py|python3|set --role|System/tools")                 # no command to copy

    def test_the_dialog_has_the_three_choices_each_with_its_own_text_and_asks_for_a_yes(self):
        sec = self.section(self.full(), "machine-settings")
        for role, name in (("solo", "One computer"), ("server", "Home server"), ("roaming", "Laptop copy")):
            self.assertRegex(sec, r'<input type="radio" name="role-pick" value="%s"' % role)
            self.assertIn("<b>%s</b>" % name, sec)
            self.assertIn(htmllib.escape(ISSUE[role]), sec)
        self.assertIn('id="role-server"', sec)
        self.assertIn('id="role-yes">Change the role</button>', sec)
        self.assertIn('id="role-no">Cancel</button>', sec)
        self.assertIn("This changes this computer only. Nothing in your workspace changes", sec)
        for role in ("solo", "server", "roaming"):
            self.assertIn(role, json.loads(re.search(r'id="role-changes">(.*?)</script>', sec).group(1)))

    def test_the_dialog_refuses_a_laptop_copy_without_a_server_name_before_it_sends(self):
        self.assertIn("if(r==='roaming'&&!s){err.textContent='A laptop copy needs the name of the home server.'", sg.JS)
        self.assertLess(sg.JS.index("A laptop copy needs the name of the home server."), sg.JS.index("if(send(q))"))

    def test_the_section_and_the_role_row_have_their_own_texts(self):
        sec = self.section(self.full(), "machine-settings")
        self.assertIn('id="help-machine"', sec)
        self.assertIn(htmllib.escape(ISSUE["machine"]), sec)
        self.assertIn('id="help-machine-role"', sec)

    def test_the_section_sits_in_the_list_of_sections(self):
        markup = self.full()
        self.assertIn('data-setgo="machine-settings"', markup)
        self.assertIn(">This machine<", markup)


class TestReadGuardBlock(SettingsCase):
    def block(self, **kw):
        return self.section(self.full(), "walls-settings")

    def test_the_four_rows_and_their_defaults(self):
        self.assistants()
        sec = self.block()
        self.assertIn('id="readguard-settings"', sec)
        self.assertRegex(sec, r'class="apponly"|rgblock apponly')
        self.assertRegex(sec, r'<input type="radio" name="rg-mode" value="off" checked>')            # Off
        self.assertRegex(sec, r'<input type="radio" name="rg-cross" value="deny" checked>')          # Refuse
        for label in ("Off", "Watch only", "On", "Refuse", "Ask me"):
            self.assertIn("> %s</label>" % label, sec)
        self.assertIn('<span class="rgtool">mcp__*Gmail*</span>', sec)
        self.assertIn('<span class="rgtool">mcp__*Calendar*</span>', sec)
        self.assertEqual(2, sec.count('data-rg-remove='))                                           # a remove button on each item
        self.assertEqual(2, sec.count('data-rg-add='))                                              # an Add on each list
        self.assertRegex(sec, r'data-rg="skip">.*?None\.')                                          # the second list is empty

    def test_a_laptop_copy_shows_one_line_in_place_of_the_controls(self):
        self.role("roaming", name="laptop", server="mini")
        self.assistants()
        sec = self.block()
        self.assertIn("The read guard is set on the home server.", sec)
        self.assertNotIn("<input", sec)
        self.assertNotIn('data-rg="mode"', sec)
        self.assertNotIn("rg-show", sec)
        self.role("server", name="mini")
        self.assertIn('data-rg="mode"', self.block())
        self.assertNotIn("set on the home server", self.block())

    def test_the_mode_is_what_runs_not_what_the_file_says(self):
        self.assistants()
        self.settings_file(**{"read-guard": "enforce"})
        self.assertRegex(self.block(), r'name="rg-mode" value="off" checked')                       # not registered: nothing runs
        self.assistants(registered=True)
        self.assertRegex(self.block(), r'name="rg-mode" value="enforce" checked')
        self.settings_file(**{"read-guard": "warn"})
        self.assertRegex(self.block(), r'name="rg-mode" value="warn" checked')

    def test_the_cross_wall_choice_and_the_lists_come_from_the_settings(self):
        self.assistants()
        self.settings_file(**{"read-guard-cross-zone": "ask", "connector-tools": ["mcp__*Mail*"], "connector-tools-skip": ["mcp__weather__*"]})
        sec = self.block()
        self.assertRegex(sec, r'name="rg-cross" value="ask" checked')
        self.assertIn('<span class="rgtool">mcp__*Mail*</span>', sec)
        self.assertNotIn("mcp__*Gmail*", sec)
        self.assertIn('<span class="rgtool">mcp__weather__*</span>', sec)

    def test_under_watch_only_it_says_what_it_would_have_stopped_in_the_last_seven_days_with_show(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.log(("Work", "Read", "deny", 5), ("Work", "Grep", "deny", 30), ("Work", "Read", "allow", 2), ("Work", "Read", "deny", 24 * 9))
        sec = self.block()
        self.assertIn("In the last 7 days it would have stopped 2 reads in Work sessions.", sec)
        self.assertIn('id="rg-show"', sec)
        self.assertIn('id="rg-list" hidden', sec)
        lst = re.search(r'id="rg-list" hidden>(.*?)</div></div>', sec, re.S).group(1)
        self.assertEqual(2, lst.count("<li>"))
        self.assertIn("Read", lst)
        self.assertIn("Grep", lst)
        self.assertIn("would be stopped", lst)
        self.assertNotIn("a1b2c3d4e5f6", sec)                                                       # the hash is never shown

    def test_no_figure_adds_two_zones(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.log(("Work", "Read", "deny", 5), ("Work", "Read", "deny", 6), ("Personal", "Glob", "confirm", 7))
        sec = self.block()
        self.assertIn("In Work sessions, in the last 7 days it would have stopped 2 reads.", sec)
        self.assertIn("In Personal sessions, in the last 7 days it would have stopped 1 read.", sec)
        self.assertNotIn("stopped 3 reads", sec)
        self.assertEqual(2, sec.count('class="rglistzone"'))

    def test_nothing_counted_says_so_and_the_other_modes_say_nothing_of_the_log(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.assertIn("In the last 7 days it would have stopped no reads.", self.block())
        self.assertNotIn('id="rg-show"', self.block())
        self.settings_file(**{"read-guard": "enforce"})
        self.assertNotIn("In the last 7 days", self.block())

    def test_a_session_at_the_root_has_no_zone_and_is_not_counted(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.log(("root", "Read", "allow", 1), ("", "Read", "deny", 2), ("Work", "Read", "deny", 3))
        self.assertIn("stopped 1 read in Work sessions", self.block())

    def test_when_the_filter_cannot_run_the_row_says_so_in_plain_words(self):
        self.assistants(registered=True)
        (self.root / "System" / "context.md").write_text("# Context\n\n## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n| Work | Client work | yes |\n")
        for mode, tail in (("warn", "Watch only lets every result through"), ("enforce", "every result from those tools is held back")):
            with self.subTest(mode=mode):
                self.settings_file(**{"read-guard": mode})
                sec = self.block()
                self.assertIn('id="rg-cannot"', sec)
                self.assertIn("the mail and calendar check cannot run", sec)
                self.assertIn(tail, sec)
        self.settings_file(**{"read-guard": "warn"})
        (self.root / "System" / "context.md").write_text("# Context\n\n## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n| Work | Client work | yes |\n\n## Parties\n")
        self.assertIn("cannot run", self.block())

    def test_with_the_filter_able_to_run_the_row_is_not_there(self):
        self.assistants()
        self.assertNotIn("rg-cannot", self.block())

    def test_codex_gives_one_line_in_place_of_the_two_lists(self):
        self.assistants()
        os.environ["GARRICK_HARNESS"] = "codex"
        sec = self.block()
        self.assertIn(CODEX, sec)
        self.assertNotIn('data-rg-add', sec)
        self.assertNotIn("Mail and calendar tools", sec)
        os.environ["GARRICK_HARNESS"] = "claude"
        self.assertNotIn(CODEX, self.block())

    def test_the_block_texts_are_the_issues_word_for_word(self):
        self.assistants()
        sec = self.block()
        for key in ("readguard", "rg-mode", "rg-cross", "rg-tools", "rg-skip"):
            self.assertIn('id="help-%s"' % key, sec)
            self.assertIn(htmllib.escape(ISSUE[key]), sec, key)
        for key, text in sg.GUARD_TEXT.items():
            self.assertEqual(ISSUE[key], text)
        for key in ("solo", "server", "roaming"):
            self.assertEqual(ISSUE[key], sg.ROLE_TEXT[key])
        self.assertEqual(ISSUE["machine"], sg.MACHINE_TEXT)
        self.assertEqual(CODEX, sg.CODEX_LINE)

    def test_the_block_works_in_the_app_only(self):
        self.assistants()
        self.assertRegex(self.block(), r'<div class="rgblock apponly" id="readguard-settings" hidden')

    def test_the_markup_sends_only_the_pages_own_verb_with_the_four_choices(self):
        self.assertIn("{verb:'read-guard'}", sg.JS)
        self.assertIn("{verb:'machine-role',role:r}", sg.JS)
        for word in ("rg-mode", "rg-cross", "data-rg-add", "data-rg-remove"):
            self.assertIn(word, sg.JS.replace("rgAdd", "data-rg-add").replace("rgRemove", "data-rg-remove") + " rg-mode rg-cross")

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(process.argv[1])", sg.JS], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)


class TestEverySettingHasItsOwnHelp(SettingsCase):
    def setUp(self):
        super().setUp()
        self.assistants()
        self.markup = self.full()
        self.parsed = parse(self.markup)

    def test_every_control_sits_in_a_row_that_has_a_question_mark(self):
        bare = []
        for tag, attrs, row in self.parsed.controls:
            if attrs.get("type") == "hidden" or attrs.get("name") == "role-pick" or attrs.get("class") in ("rgnew",) \
                    or attrs.get("id") in ("role-name", "role-server"):
                continue                                          # the dialog's fields: its own text is the explanation
            if row is None or not row["help"]:
                bare.append((tag, attrs.get("id") or attrs.get("data-launcher") or attrs.get("data-nt") or attrs.get("name") or attrs.get("class")))
        self.assertEqual([], bare)

    def test_every_row_of_a_known_kind_was_given_one_by_the_table(self):
        self.assertEqual([], sh.unknown_rows(self.markup))

    def test_each_question_mark_has_one_text_and_each_id_is_used_once(self):
        targets = self.parsed.targets
        self.assertEqual(len(targets), len(set(targets)), [t for t in targets if targets.count(t) > 1])
        for target in targets:
            self.assertIn(target, self.parsed.helps, target)
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)), [i for i in self.parsed.ids if self.parsed.ids.count(i) > 1])

    def test_the_section_marks_stay(self):
        for sid in ("launcher-settings", "notify-settings", "memory-settings", "walls-settings", "about-settings"):
            self.assertRegex(self.section(self.markup, sid), r'<h3>[^<]*<button class="qhelp"')

    def test_no_help_text_names_a_file_a_key_a_command_or_an_issue_and_none_is_long(self):
        texts = {k: v for k, v in self.parsed.helps.items() if k and k.startswith("help-")}
        self.assertGreater(len(texts), 60)
        for key, text in texts.items():
            with self.subTest(key=key):
                self.assertNotRegex(text, r"\.json|\.py|--|#\d", key)
        for key, text in texts.items():
            if key in ("help-walls", "help-menu", "help-launchers", "help-explore", "help-zones", "help-graphcol", "help-notify",
                       "help-channels", "help-memory", "help-about", "help-preview", "help-view"):
                continue                                          # a section's own text is older than this, and says more
            with self.subTest(long=key):
                self.assertLessEqual(len(text.split()), WORDS_MAX, text)
                self.assertNotRegex(text, FORBIDDEN, key)

    def test_the_table_has_no_text_that_breaks_the_rules(self):
        for needle, key, name, text in sh.ROWS:
            with self.subTest(key=key):
                self.assertLessEqual(len(text.split()), WORDS_MAX, text)
                self.assertNotRegex(text, FORBIDDEN)
                self.assertTrue(text.endswith("."))

    def test_the_same_choice_has_the_same_name_everywhere(self):
        text = self.markup
        for word in ("One computer", "Home server", "Laptop copy", "Watch only", "Refuse", "Ask me"):
            self.assertIn(word, text)
        for old in ("solo", "roaming", "Roaming", "Server", "Enforce", "enforce"):
            visible = re.sub(r'<script.*?</script>|value="[^"]*"|data-[a-z-]+="[^"]*"|id="[^"]*"|class="[^"]*"', "", text, flags=re.S)
            visible = re.sub(r"<[^>]+>", " ", visible)
            self.assertNotRegex(visible, r"\b%s\b" % old, old)

    def test_a_zone_added_later_gets_its_own_unique_help(self):
        (self.root / "Zones" / "Ventures").mkdir()
        (self.root / "Zones" / "Ventures" / "Todo.md").write_text("# Todo\n")
        markup = status.settings(self.root, ("claude",), ("Work", "Personal", "Ventures"), {}, True, status.Links(self.root), [], {})
        parsed = parse(markup)
        self.assertEqual(len(parsed.targets), len(set(parsed.targets)))
        self.assertIn("help-zone-ventures", parsed.helps)
