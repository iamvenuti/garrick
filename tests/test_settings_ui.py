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
import settings_readguard as rgs  # noqa: E402

# The texts of #621, word for word.
ISSUE = {
    "machine": "Most people use Garrick on one computer and can leave this as it is. Change it only if your workspace lives on a computer that stays on at home and a laptop keeps a copy of it. This setting stays on this computer, so the other computer keeps its own.",
    "solo": "Everything happens here: your sessions, the nightly jobs and your Todo lists.",
    "server": "This computer is always on and holds the real workspace. The nightly jobs run here, and it applies the ticks your laptop sends.",
    "roaming": "This computer keeps a copy that only receives. You can read everything, even with no network. A tick on a Todo list waits until the home server applies it. Nightly jobs do not run here.",
    "readguard": "Walls already stop your assistant from writing one zone's material into another. The read guard does the same for reading. In a session for one project, it stops the assistant from opening notes, meetings and mail that sit behind another wall.",
    "rg-mode": "Watch lets every read through and keeps a list of what it would have stopped. Start with it for a week and look at the list. When the list holds nothing you needed, choose On, and those reads are stopped.",
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
        elif tag == "button" and "qhelp" not in classes:
            row = next((f for f in reversed(self.stack) if f["row"]), None)
            if row is not None:                                   # a button that stands in a setting row: the row needs its own "?"
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
        """A section of Settings, or a part of one (#682), by its id, whole."""
        m = re.search(r'<(section|div|details) class="(?:setsec|setpart|setfold)[^"]*" id="%s"' % re.escape(sid), markup)
        self.assertIsNotNone(m, sid)
        return markup[m.start():sh.find_close(markup, m.start(), m.group(1))]


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
        self.assertRegex(sec, r'<button class="act sm apponly"[^>]*id="role-change"')
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

    def test_the_row_has_one_text_and_says_the_role_once(self):
        sec = self.section(self.full(), "machine-settings")
        self.assertIn('id="help-machine"', sec)
        self.assertIn(htmllib.escape(rgs.MACHINE_TEXT), sec)
        self.assertEqual("Change this only if a second computer keeps a copy of your workspace.", rgs.MACHINE_TEXT)   # #681's text
        self.assertNotIn('id="help-machine-role"', sec)
        row = sec[:sec.index('id="role-dialog"')]
        self.assertEqual(1, row.count(htmllib.escape(ISSUE["solo"])))            # the role's sentence, once: its tooltip (#681, #682)
        self.assertIn('title="%s"' % htmllib.escape(ISSUE["solo"]), row)

    def test_this_computer_is_a_row_in_about_with_no_entry_of_its_own(self):
        markup = self.full()
        self.assertNotIn('data-setgo="machine-settings"', markup)
        about = self.section(markup, "about-settings")
        self.assertIn('id="machine-settings"', about)
        self.assertRegex(about, r'class="launcher-row srow mrole" id="machine-role"[^>]*><div class="slab"><span class="launcher-choice"><span>This computer</span>')
        self.assertIn('<h3 id="role-title" tabindex="-1">This computer</h3>', about)


class TestReadGuardBlock(SettingsCase):
    def block(self, **kw):
        return self.section(self.full(), "readguard-settings")        # a part of Walls since 0.80.0 (#682)

    def test_the_four_rows_and_their_defaults(self):
        self.assistants()
        sec = self.block()
        self.assertIn('id="readguard-settings"', sec)
        self.assertRegex(sec, r'setpart apponly')
        self.assertRegex(sec, r'<input type="radio" name="rg-mode" value="off" checked>')            # Off
        self.assertRegex(sec, r'<input type="radio" name="rg-cross" value="deny" checked>')          # Refuse
        for label in ("Off", "Watch", "On"):
            self.assertIn("<b>%s</b>" % label, sec)
        for label in ("Refuse", "Ask me"):
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

    def claude_only(self):
        """The guard is registered for Claude Code, and the Codex folder is there with nothing in it."""
        (self.home / ".claude").mkdir(exist_ok=True)
        sg.guard_module().register(str(REPO / "extras" / "hooks" / "read_guard.py"), str(self.home))
        (self.home / ".codex").mkdir(exist_ok=True)

    def test_a_claude_only_registration_beside_an_empty_codex_folder_shows_the_mode_as_set(self):
        self.claude_only()
        self.assertEqual([], list((self.home / ".codex").iterdir()))
        for mode in ("warn", "enforce"):
            self.settings_file(**{"read-guard": mode})
            self.assertRegex(self.block(), r'name="rg-mode" value="%s" checked' % mode)

    def test_an_assistant_that_is_installed_without_the_guard_keeps_it_off(self):
        self.claude_only()
        (self.home / ".codex" / "config.toml").write_text("model = 'x'\n")                 # Codex is here, and has no hook
        self.settings_file(**{"read-guard": "enforce"})
        self.assertRegex(self.block(), r'name="rg-mode" value="off" checked')               # fail closed: never On for what is not set up

    def test_no_registration_in_any_assistant_is_off_whatever_the_file_says(self):
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        self.settings_file(**{"read-guard": "enforce"})
        self.assertRegex(self.block(), r'name="rg-mode" value="off" checked')

    def test_settings_that_do_not_read_show_On_with_a_line_that_says_so(self):
        self.assistants(registered=True)
        (self.root / "System" / "garrick-settings.json").write_text("{not json")
        sec = self.block()
        self.assertRegex(sec, r'name="rg-mode" value="enforce" checked')
        self.assertIn("Garrick cannot read your settings file.", sec)
        self.settings_file(**{"read-guard": "warn"})
        sec = self.block()
        self.assertRegex(sec, r'name="rg-mode" value="warn" checked')
        self.assertNotIn("cannot read your settings file", sec)

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
        self.assertIn("In the last 7 days it would have stopped 2 files in Work.", sec)
        self.assertIn('id="rg-show"', sec)
        self.assertIn('id="rg-list" hidden', sec)
        lst = re.search(r'id="rg-list" hidden>(.*?)</div></div>', sec, re.S).group(1)
        self.assertEqual(2, lst.count('<li class="rgread">'))
        self.assertIn("Read", lst)
        self.assertIn("Grep", lst)
        self.assertIn("not recorded", lst)                                                         # a line 0.78.0 wrote has no file (#674)
        self.assertNotIn("a1b2c3d4e5f6", sec)                                                       # the hash is never shown

    def test_no_figure_adds_two_zones(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.log(("Work", "Read", "deny", 5), ("Work", "Read", "deny", 6), ("Personal", "Glob", "confirm", 7))
        sec = self.block()
        self.assertIn("In the last 7 days it would have stopped 1 file in Work.", sec)           # two reads of one file fold into one
        self.assertIn("In the last 7 days it would have stopped 1 file in Personal.", sec)
        self.assertNotIn("stopped 3 files", sec)
        self.assertEqual(2, sec.count('class="rglistzone"'))

    def test_nothing_counted_says_so_and_the_other_modes_say_nothing_of_the_log(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.assertIn("In the last 7 days it would have stopped nothing.", self.block())
        self.assertNotIn('id="rg-show"', self.block())
        self.settings_file(**{"read-guard": "enforce"})
        self.assertNotIn("In the last 7 days", self.block())

    def test_a_session_at_the_root_has_no_zone_and_is_not_counted(self):
        self.assistants(registered=True)
        self.settings_file(**{"read-guard": "warn"})
        self.log(("root", "Read", "allow", 1), ("", "Read", "deny", 2), ("Work", "Read", "deny", 3))
        self.assertIn("stopped 1 file in Work", self.block())

    def test_when_the_filter_cannot_run_the_row_says_so_in_plain_words(self):
        self.assistants(registered=True)
        (self.root / "System" / "context.md").write_text("# Context\n\n## Zones\n\n| Zone | Holds | Walled |\n|---|---|---|\n| Work | Client work | yes |\n")
        for mode, tail in (("warn", "Watch lets every result through"), ("enforce", "every result from those tools is held back")):
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
        self.assertIn(htmllib.escape(rgs.CODEX_TRUST), sec)
        self.assertNotIn("hooks", rgs.CODEX_TRUST)                                              # no internal part (#681)
        self.assertNotIn('data-rg-add', sec)
        self.assertNotIn("Mail and calendar tools", sec)
        os.environ["GARRICK_HARNESS"] = "claude"
        self.assertNotIn(CODEX, self.block())
        self.assertNotIn("rg-trust", self.block())

    def test_the_block_texts_are_the_issues_word_for_word(self):
        self.assistants()
        sec = self.block()
        for key, text in (("readguard", rgs.HELP_TEXT), ("rg-tools", rgs.TOOLS_TEXT)):   # #681: two texts, the lists sharing one
            self.assertIn('id="help-%s"' % key, sec)
            self.assertIn(htmllib.escape(text), sec, key)
        for key in ("rg-cross", "rg-skip"):
            self.assertNotIn('id="help-%s"' % key, sec)
        self.assertIn("This starts when you choose On.", sec)
        self.assertIn("The assistant does not read what sits behind the wall of another zone.", sec)
        for key, text in sg.GUARD_TEXT.items():
            self.assertEqual(ISSUE[key], text)
        for key in ("solo", "server", "roaming"):
            self.assertEqual(ISSUE[key], sg.ROLE_TEXT[key])
        self.assertEqual(ISSUE["machine"], sg.MACHINE_TEXT)
        self.assertEqual(CODEX, sg.CODEX_LINE)

    def test_the_block_works_in_the_app_only_and_is_a_part_of_walls(self):
        self.assistants()
        self.assertRegex(self.block(), r'<div class="setpart apponly" id="readguard-settings" hidden')
        walls = self.section(self.full(), "walls-settings")
        self.assertIn('id="readguard-settings"', walls)
        self.assertLess(walls.index('class="wallrows"'), walls.index('id="readguard-settings"'))      # after the zones
        self.assertIn('<h4 class="setsubh">Read guard<button class="qhelp"', walls)

    def test_the_markup_sends_only_the_pages_own_verb_with_the_four_choices(self):
        self.assertIn("{verb:'read-guard'}", sg.JS)
        self.assertIn("{verb:'machine-role',role:r}", sg.JS)
        for word in ("rg-mode", "rg-cross", "data-rg-add", "data-rg-remove"):
            self.assertIn(word, sg.JS.replace("rgAdd", "data-rg-add").replace("rgRemove", "data-rg-remove") + " rg-mode rg-cross")

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_the_script_parses(self):
        done = subprocess.run(["node", "-e", "new Function(process.argv[1])", sg.JS], capture_output=True, text=True, timeout=30)
        self.assertEqual(0, done.returncode, done.stderr)


# #681: what a help text may not hold, the words the dialog never shows, and one term per thing.
FORBIDDEN_681 = ("launchd", "plist", "GARRICK_NOTIFY", "hooks", "frontmatter", "pinned: true", "published:", "date:", "garrick-flags.json",
                 "model calls", "end-to-end", "the cmux extra")
NOT_A_WORD_HERE = ("notice", "hotkey", "machine", "fade", "digest")
TEXT_RULE = re.compile(r"`|__|\.json|\b[A-Z]+_[A-Z_]+\b")
# What choices-0800 replaces (#683), skipped by name until it is in: the read guard's fold of tool patterns, named
# "Which connected tools are checked" (it becomes "Connected services").
CHOICES_ROWS = ("Which connected tools are checked",)
# A sentence #681 gives word for word that runs past a limit of its rule: the conditions and the Walls line.
GIVEN = ("Not set up yet. Ask your assistant to set up notifications.",
         "A walled zone keeps its material to itself. Material from an open zone may go anywhere.",
         "A working page is used in every answer. A dormant page is used only when a search reaches back. An archived page is used "
         "only when you ask for it.",
         "Walls stop your assistant from writing across zones. The read guard stops it from reading across zones. Start with Watch "
         "for a week, then choose On.")


def visible(markup):
    """The dialog's words as a reader meets them: no script, no attribute."""
    return htmllib.unescape(re.sub(r"<script.*?</script>|<[^>]+>", " ", markup, flags=re.S))


class TestOneShortHelpText(SettingsCase):
    """#681: one short help text per thing, and none where the label says it."""

    def setUp(self):
        super().setUp()
        self.assistants()
        self.markup = self.full()
        self.parsed = parse(self.markup)

    def texts(self, markup=None):
        return {k: htmllib.unescape(v) for k, v in (parse(markup).helps if markup else self.parsed.helps).items() if k and k.startswith("help-")}

    def test_no_text_is_over_thirty_words_or_two_sentences_and_none_breaks_the_rule(self):
        texts = self.texts()
        self.assertTrue(texts)
        for key, text in texts.items():
            with self.subTest(key=key):
                self.assertLessEqual(len(text.split()), 30, text)
                if text not in GIVEN:                       # #681's own texts for Older pages and the read guard have three
                    self.assertLessEqual(len(re.findall(r"[.!?](\s|$)", text)), 2, text)
                self.assertNotRegex(text, TEXT_RULE)
                for word in FORBIDDEN_681:
                    self.assertNotIn(word, text)

    def test_the_rule_fails_on_a_text_that_breaks_it(self):
        for bad in (" ".join(["word"] * 31), "Set `x`.", "See mcp__x.", "In System/garrick-settings.json.", "Set GARRICK_NOTIFY first."):
            self.assertTrue(len(bad.split()) > 30 or TEXT_RULE.search(bad), bad)
        for needle, key, name, text in sh.ROWS:
            with self.subTest(key=key):
                self.assertLessEqual(len(text.split()), 30)
                self.assertNotRegex(text, TEXT_RULE)
                self.assertTrue(text.endswith("."))

    def test_at_most_twenty_five_texts_in_a_workspace_of_any_size(self):
        self.assertLessEqual(len(self.texts()), 25)
        (self.root / "Zones" / "Ventures").mkdir()
        (self.root / "Zones" / "Ventures" / "Todo.md").write_text("# Todo\n")
        more = status.settings(self.root, ("claude", "codex"), ("Work", "Personal", "Ventures", "Harbour"), {}, True, status.Links(self.root),
                               [("project", "Project", "Teal"), ("thread", "Thread", "Indigo"), ("meeting", "Meeting", "Olive")], {})
        self.assertEqual(len(self.texts()), len(self.texts(more)))            # a zone, a wiki or a kind of page adds none

    def test_two_rows_of_one_section_never_carry_the_same_text(self):
        for sec in re.findall(r'<section class="setsec.*?</section>', self.markup, re.S):
            said = list(self.texts(sec).values())
            self.assertEqual(len(said), len(set(said)), said)

    def test_no_forbidden_string_in_the_dialog_and_no_old_word_in_a_label_a_line_or_a_text(self):
        for markup in (self.markup, self.cmux_rich()):
            seen = visible(markup)
            for word in FORBIDDEN_681:
                self.assertNotIn(word, seen)
            for word in NOT_A_WORD_HERE:
                self.assertNotRegex(seen.lower(), r"\b%s" % word)

    def cmux_rich(self):
        cmux = Path(self._tmp.name) / "cmuxlib.py"
        cmux.write_text("")
        with mock.patch.object(status, "CMUXLIB", cmux):
            return status.settings(self.root, ("claude", "codex", "cmux"), ("Work",), {}, True, status.Links(self.root), [("project", "Project", "Teal")], {})

    def test_no_row_says_the_same_sentence_in_its_line_and_its_text(self):
        for row in re.findall(r'<div class="launcher-row srow.*?</div></div>(?:<button class="qhelp".*?</button></div><p class="hint sethelp"[^>]*>.*?</p>)?', self.markup, re.S):
            small = re.findall(r"<small[^>]*>(.*?)</small>", row)
            text = re.findall(r'class="hint sethelp"[^>]*>(.*?)</p>', row)
            for line in small:
                for t in text:
                    for sentence in re.split(r"(?<=\.)\s+", htmllib.unescape(line)):
                        if sentence.strip():
                            self.assertNotIn(sentence.strip(), htmllib.unescape(t))

    def test_small_lines_are_ten_words_and_section_lines_fifteen(self):
        for line in re.findall(r"<small[^>]*>(.*?)</small>", self.markup):
            line = htmllib.unescape(re.sub(r"<[^>]+>", "", line))
            if line in GIVEN or line.startswith("Installed, but"):
                continue
            if "rolechoice" in self.markup and line in sg.ROLE_TEXT.values():
                continue                                    # the role window's choices, each with its line
            if line in rgs.MODE_SAID.values():
                continue                                    # the read guard's choices, each with its line (#674)
            self.assertLessEqual(len(line.split()), 10, line)
        for lede in re.findall(r'</h3><p class="setlede">(.*?)</p>', self.markup):
            lede = htmllib.unescape(lede)
            if lede not in GIVEN:
                self.assertLessEqual(len(lede.split()), 15, lede)

    def test_saving_is_said_once_at_the_foot(self):
        seen = visible(self.markup)
        self.assertEqual(1, len(re.findall(r"\b[Ss]ave[sd]?\b", seen)), re.findall(r".{30}\b[Ss]ave[sd]?\b.{20}", seen))
        self.assertIn('<p class="setfootsay" id="settings-saved">Garrick saves your changes.</p></div>', self.markup)

    def test_a_row_without_a_question_mark_is_no_failure_and_the_known_ones_have_one(self):
        self.assertTrue(sh.unknown_rows(self.markup))                     # many rows have none, on purpose
        for key in ("launchers", "notify", "memory", "walls", "zones", "readguard", "menu-show", "menu-ask", "ch-tier", "ch-autonomy",
                    "nt-needs-you", "nt-quiet", "mem-wake", "rel-on", "usage-on", "machine", "about"):
            self.assertIn("help-" + key, self.parsed.helps, key)
        for gone in ("launch-note", "launch-claude", "menu-askkey", "nt-finished", "wall-work", "zone-work", "kind-project", "view",
                     "preview", "rg-cross", "rg-skip", "ch-tier-telegram", "channels", "explore", "menu"):
            self.assertNotIn("help-" + gone, self.parsed.helps, gone)
        self.assertEqual(1, sum(1 for k in self.parsed.helps if k and k.startswith("help-mem-kind")))   # rows that repeat share one

    def test_each_question_mark_has_one_text_and_each_id_is_used_once(self):
        targets = self.parsed.targets
        self.assertEqual(len(targets), len(set(targets)), [t for t in targets if targets.count(t) > 1])
        for target in targets:
            self.assertIn(target, self.parsed.helps, target)
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)), [i for i in self.parsed.ids if self.parsed.ids.count(i) > 1])

    def test_the_conditions_show_only_when_they_apply(self):
        rel = 'data-nt="release"'
        sec = self.section(self.markup, "notify-settings")
        self.assertEqual(2, sec.count(status.NT_NOT_SET_UP))              # no hook here: both rows that need one say so
        self.assertIn(status.NT_RELEASE_OFF, sec)                          # the check for updates is off by default
        self.assertRegex(sec, r'data-nt="release" id="nt-release" disabled')
        self.settings_file(**{"release-notice": True})
        guard = sg.guard_module()
        notify = __import__("importlib").util.spec_from_file_location("n681", str(REPO / "template" / "System" / "tools" / "notifications.py"))
        mod = __import__("importlib").util.module_from_spec(notify)
        notify.loader.exec_module(mod)
        mod.hooks(self.root, self.home, install=True)
        sec = self.section(self.full(), "notify-settings")
        self.assertNotIn("Not set up yet", sec)
        self.assertNotIn("Turn on Check for updates", sec)
        self.assertNotIn("%s id=\"nt-release\" disabled" % rel, sec)
        self.assertIsNotNone(guard)

    def test_the_morning_summary_row_only_where_notifications_keep_its_choice(self):
        doc = status._data(self.root, None, "notifications")
        sec = status.notify_settings(self.root, False, doc)
        self.assertNotIn("Morning summary", sec)                           # notifications.py does not know the key yet
        doc["notifications"]["settings"]["morning"] = "all"
        sec = status.notify_settings(self.root, False, doc)
        self.assertIn('<span>Morning summary</span>', sec)
        self.assertIn('<option value="all" selected>One for all zones</option><option value="each">One for each zone</option>', sec)
        self.assertNotIn(status.NT_MORNING_LINE, sec)
        self.assertNotIn("qhelp", sec[sec.index("Morning summary"):sec.index("</select>", sec.index("Morning summary"))])
        doc["notifications"]["own_way"] = {"todo-summary": "x"}
        del doc["notifications"]["settings"]["morning"]
        self.assertIn(status.NT_MORNING_LINE, status.notify_settings(self.root, False, doc))
        self.assertIn("var mo=document.getElementById('n-morning');if(mo)r.morning=mo.value;", status.NOTIFY_JS)

    def test_one_term_per_thing(self):
        seen = visible(self.markup)
        for skip in CHOICES_ROWS:
            seen = seen.replace(skip, "")
        for word in ("Shortcut", "this computer", "dormant", "Archived after", "notification"):
            self.assertIn(word, seen)
        for old in ("Hotkey", "this Mac", "connected tool", "morning digest", "gone quiet", "out of everyday answers"):
            self.assertNotIn(old, seen)

    def test_the_section_marks_stay_where_a_section_has_one(self):
        for sid in ("launcher-settings", "notify-settings", "walls-settings", "look-settings"):
            self.assertRegex(self.section(self.markup, sid), r'<h3>[^<]*<button class="qhelp"')
        for sid in ("ask-settings", "about-settings"):
            self.assertNotRegex(self.section(self.markup, sid), r'<h3>[^<]*<button class="qhelp"')

    def test_the_same_choice_has_the_same_name_everywhere(self):
        text = self.markup
        for word in ("One computer", "Watch", "Refuse", "Ask me"):
            self.assertIn(word, text)
        for old in ("solo", "roaming", "Roaming", "Server", "Enforce", "enforce"):
            visible_ = re.sub(r'<script.*?</script>|value="[^"]*"|data-[a-z-]+="[^"]*"|id="[^"]*"|class="[^"]*"', "", text, flags=re.S)
            visible_ = re.sub(r"<[^>]+>", " ", visible_)
            self.assertNotRegex(visible_, r"\b%s\b" % old, old)
