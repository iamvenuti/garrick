"""The read guard in Settings, for a business user (#674): one heading, three choices each with its consequence, a list that names
what would have been stopped, Across a wall only under On, and the connected services by name in a closed fold of their own (#683).

    cd tests && python3 -m unittest test_read_guard_list

Part one runs the hook on a fictional workspace (three zones: Work and Personal walled, Ventures open) and reads what a logged
line records: the session's project, the file's path from the workspace and its zone, or the connector for a mail result, and
never a file's or a message's content. Part two draws the list from lines, those and the ones 0.78.0 wrote.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.dont_write_bytecode = True

from read_guard_case import REPO, GuardCase  # noqa: E402

sys.path.insert(0, str(REPO / "extras" / "status"))
import settings_guard as sg  # noqa: E402
import settings_readguard as rgs  # noqa: E402

NOW = dt.datetime(2026, 11, 23, 16, 0, 0)
STATE = {"registered": True, "mode": "warn", "cross": "deny", "tools": ["mcp__*Gmail*"], "skip": [], "problem": "", "would": {}, "unreadable": False}


def button(name, key):
    return '<button class="qhelp" type="button" aria-controls="help-%s">?</button>' % key


def text(name, key):
    return '<p class="hint sethelp" id="help-%s" hidden>%s</p>' % (name, key)


def line(minutes, tool="Read", decision="deny", zone="Work", **more):
    when = (NOW - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    return dict({"t": when, "tool": tool, "decision": decision, "zone": zone, "id": "a1b2c3d4e5f6"}, when=dt.datetime.strptime(when, "%Y-%m-%dT%H:%M:%S"),
                **more)


def would(lines):
    return sg.would_have_stopped(sorted(lines, key=lambda i: i["when"], reverse=True))


OPEN = {"walled": {"Work": False, "Personal": False, "Ventures": False}}          # every zone open: the list may name any file


def block(lines=(), mode="warn", shown=OPEN, **kw):
    state = dict(STATE, mode=mode, would={z: [dict(i, when=i["when"].isoformat()) for i in items] for z, items in would(list(lines)).items()}, **kw)
    return rgs.guard_block(sg, state, False, button, text, "solo", **({"shown": shown} if shown is not None else {}))


class Tags(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.out, self.stack = [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.out.append((tag, dict(attrs), list(self.stack)))
        if tag not in ("input", "br", "img", "meta", "link"):
            self.stack.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def visible_text(markup):
    """The words a reader sees: what is not hidden, not in a closed fold."""
    markup = markup.replace('id="readguard-settings" hidden', 'id="readguard-settings"')      # the section opens once the app answers

    class Words(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.hide, self.words, self.stack = 0, [], []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            closed = tag == "details" and "open" not in a
            if tag not in ("input", "br", "img", "meta", "link"):
                self.stack.append(("hidden" in a or closed))
                self.hide += 1 if ("hidden" in a or closed) else 0

        def handle_endtag(self, tag):
            if self.stack:
                if self.stack.pop():
                    self.hide -= 1

        def handle_data(self, data):
            if not self.hide and data.strip():
                self.words.append(data.strip())
    w = Words()
    w.feed(markup)
    return " ".join(w.words)


class TestWhatALineRecords(GuardCase):
    """The hook's log: when, the tool, the decision and the session's zone as before, and now the project, the file and its zone."""

    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "warn"})
        self.start(self.acme)

    def test_a_read_of_another_zones_file_records_the_project_the_file_and_its_zone(self):
        for _ in range(3):
            self.read(self.birch / "Notes" / "secret.md")
        lines = self.log_lines()
        self.assertEqual(3, len(lines))
        first = lines[0]
        self.assertEqual("Work", first["zone"])
        self.assertEqual("Acme", first["project"])
        self.assertEqual("Zones/Personal/Birch/Notes/secret.md", first["file"])
        self.assertEqual("Personal", first["file_zone"])
        self.assertEqual("Zones", first["part"])
        self.assertEqual("deny", first["decision"])
        self.assertEqual(1, len({l["session"] for l in lines}))             # one session, so the list can fold them
        self.assertEqual(3, len({l["t"] + str(i) for i, l in enumerate(lines)}))

    def test_a_file_in_system_or_in_a_wiki_says_which_part(self):
        self.read(self.root / "System" / "notes.md")
        self.read(self.root / "Wikis" / "Meetings" / "wiki" / "birch-pricing.md")
        out = {l["file"]: l for l in self.log_lines()}
        self.assertEqual("System", out["System/notes.md"]["part"])
        meeting = out["Wikis/Meetings/wiki/birch-pricing.md"]
        self.assertEqual("Wikis", meeting["part"])
        self.assertEqual("Personal", meeting["file_zone"])

    def test_a_file_outside_the_workspace_is_logged_as_outside_and_never_with_its_path(self):
        outside = self.root.parent / "elsewhere" / "private-notes.md"
        outside.parent.mkdir()
        outside.write_text("x")
        self.call("Bash", {"command": "cat %s %s" % (outside, self.birch / "Notes" / "secret.md")})
        text = self.log_text()
        self.assertNotIn("private-notes", text)
        self.assertNotIn(str(outside.parent), text)
        self.assertNotIn(str(self.root), text)                            # never an absolute path of this computer
        self.assertIn('"file": "Zones/Personal/Birch/Notes/secret.md"', text)

    def test_a_line_never_holds_what_a_file_says(self):
        (self.birch / "Notes" / "secret.md").write_text("The renewal floor is a private figure.")
        self.read(self.birch / "Notes" / "secret.md")
        self.assertNotIn("private figure", self.log_text())


class TestWhatAMailLineRecords(GuardCase):
    def test_a_held_back_mail_result_names_the_tool_the_source_and_the_zone_and_nothing_of_the_message(self):
        self.settings(**{"read-guard": "warn", "connector-tools": ["mcp__fakemail__*"]})
        self.start(self.acme)
        threads = [{"id": "t2", "from": "Theo <theo@birch.example>", "to": ["jo@home.example"], "subject": "Birch pricing", "snippet": "The floor is 40"}]
        self.run_hook({"session_id": "c1", "hook_event_name": "PostToolUse", "tool_name": "mcp__fakemail__search", "cwd": str(self.acme),
                       "tool_input": {}, "tool_response": [{"type": "text", "text": json.dumps({"threads": threads})}]}, project_dir=self.acme)
        mail = [l for l in self.log_lines() if l["tool"] == "mcp__fakemail__search"]
        self.assertTrue(mail)
        self.assertEqual("fakemail", mail[0]["source"])
        self.assertEqual("Personal", mail[0]["held_zone"])
        self.assertEqual("Acme", mail[0]["project"])
        for word in ("Theo", "birch.example", "Birch pricing", "The floor"):
            self.assertNotIn(word, self.log_text())


class TestAMailTextIsNeverAFile(GuardCase):
    def test_an_unparsed_result_that_is_a_workspace_path_is_logged_as_no_file(self):
        self.settings(**{"read-guard": "warn", "connector-tools": ["mcp__fakemail__*"]})
        self.start(self.acme)
        path = str(self.birch / "Notes" / "secret.md")
        self.run_hook({"session_id": "c1", "hook_event_name": "PostToolUse", "tool_name": "mcp__fakemail__search", "cwd": str(self.acme),
                       "tool_input": {}, "tool_response": [{"type": "text", "text": path}]}, project_dir=self.acme)
        lines = [l for l in self.log_lines() if l["tool"] == "mcp__fakemail__search"]
        self.assertTrue(lines)
        for l in lines:
            self.assertNotIn("file", l)
            self.assertNotIn("outside", l)
        self.assertNotIn("secret.md", self.log_text())


class TestTheList(unittest.TestCase):
    def test_a_line_from_0780_for_a_connector_counts_as_a_result_not_a_file(self):
        markup = block([line(5, tool="mcp__fakemail__search")])
        said = " ".join(re.sub(r"<[^>]+>", " ", markup).split())
        self.assertIn("1 mail or calendar result", said)
        self.assertNotIn("1 file", said)

    def test_three_reads_of_one_file_in_one_session_fold_into_one_line_with_a_count(self):
        reads = [line(m, project="Acme", session="s1", file="Zones/Personal/Birch/Notes/secret.md", file_zone="Personal", part="Zones")
                 for m in (5, 30, 90)]
        markup = block(reads)
        items = re.findall(r"<li class=\"rgread\".*?</li>", markup, re.S)
        self.assertEqual(1, len(items))
        said = visible_text(items[0]) if False else re.sub(r"<[^>]+>", " ", items[0])
        said = " ".join(said.split())
        for part in ("23 Nov 15:55", "Acme", "Zones/Personal/Birch/Notes/secret.md", "Personal", "3 times"):
            self.assertIn(part, said)
        self.assertIn("1 file across 1 session in Work", re.sub(r"<[^>]+>", "", markup))        # files and sessions, never reads

    def test_two_sessions_and_two_files_are_counted_as_such(self):
        markup = block([line(5, session="s1", project="Acme", file="Zones/Personal/Birch/Notes/a.md", file_zone="Personal", part="Zones"),
                        line(6, session="s2", project="Acme", file="Zones/Personal/Birch/Notes/a.md", file_zone="Personal", part="Zones"),
                        line(7, session="s2", project="Acme", file="Zones/Personal/Birch/Notes/b.md", file_zone="Personal", part="Zones")])
        self.assertIn("3 files across 2 sessions in Work", re.sub(r"<[^>]+>", "", markup))

    def test_a_mail_line_shows_the_tool_and_the_zone_held_back_and_nothing_else(self):
        markup = block([line(5, tool="mcp__claude_ai_Acmemail__search", service="Acmemail", session="s1", project="Acme", held_zone="Personal")])
        item = re.search(r"<li class=\"rgread\".*?</li>", markup, re.S).group(0)
        said = " ".join(re.sub(r"<[^>]+>", " ", item).split())
        self.assertIn("Acmemail, a mail or calendar result", said)                   # the service by its plain name (#683)
        self.assertNotIn("mcp__", said)
        self.assertIn("Personal", said)
        markup = block([line(5, tool="mcp__claude_ai_Acmemail__search", session="s1", project="Acme", held_zone="Personal")])
        self.assertNotIn("mcp__", markup)                                             # a line with no name says "a connected service"

    def test_a_line_written_by_0780_still_shows_with_not_recorded_in_place_of_the_file(self):
        markup = block([line(5, tool="Bash")])
        item = re.search(r"<li class=\"rgread\".*?</li>", markup, re.S).group(0)
        said = " ".join(re.sub(r"<[^>]+>", " ", item).split())
        self.assertIn("not recorded", said)
        self.assertIn("23 Nov 15:55", said)

    def test_a_file_outside_the_workspace_says_so(self):
        markup = block([line(5, session="s1", project="Acme", outside=True)])
        self.assertIn("outside the workspace", re.sub(r"<[^>]+>", "", markup))

    def test_a_file_in_system_or_a_wiki_says_which_part(self):
        markup = block([line(5, session="s1", project="Acme", file="System/notes.md", part="System"),
                        line(6, session="s1", project="Acme", file="Wikis/Meetings/wiki/x.md", part="Wikis", file_zone="Personal")])
        said = re.sub(r"<[^>]+>", " ", markup)
        self.assertIn("System/notes.md", said)
        self.assertIn("System", said)
        self.assertIn("Wikis/Meetings/wiki/x.md", said)

    def test_the_list_never_holds_a_file_s_contents(self):
        self.assertNotIn("content", block([line(5, session="s1", project="Acme", file="Zones/Personal/a.md", file_zone="Personal", part="Zones")]).lower().replace("contents", "x"))


class TestTheWallsOfTheList(unittest.TestCase):
    """The page can be read from any session, so the list fails closed (#674 review W1, W2): a file is named, with its project, only when
    it is in an open zone, in System/ or in Wikis/Knowledge. Two walled zones and one open."""

    LINES = [line(5, session="s1", project="Acme", file="Zones/Personal/Birch/Notes/secret.md", file_zone="Personal", part="Zones"),
             line(6, session="s1", project="Acme", file="Zones/Ventures/Cedar/Cedar.md", file_zone="Ventures", part="Zones"),
             line(7, session="s1", project="Acme", file="Zones/Work/Acme/Acme.md", file_zone="Work", part="Zones"),
             line(8, session="s1", project="Acme", file="System/notes.md", part="System"),
             line(9, session="s1", project="Acme", file="Wikis/Knowledge/wiki/standard.md", part="Wikis"),
             line(10, session="s1", project="Acme", file="Zones/Mystery/x.md", part="Zones"),
             line(11, session="s1", project="Acme", file="Zones/Unknown/y.md", file_zone="Unknown", part="Zones")]
    WALLED = {"Work": True, "Personal": True, "Ventures": False}

    def drawn(self):
        import html
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", block(self.LINES, shown={"walled": self.WALLED}))).split())

    def test_a_walled_zones_file_is_not_named_nor_its_zone_nor_the_project(self):
        said = self.drawn()
        for hidden in ("secret.md", "Acme.md", "Birch", "Zones/Mystery", "Zones/Unknown", "Unknown"):
            self.assertNotIn(hidden, said)
        self.assertEqual(4, said.count("a file behind another zone's wall"))        # two walled, one with no zone, one unknown

    def test_an_open_zone_system_and_the_knowledge_wiki_are_named(self):
        said = self.drawn()
        for shown in ("Zones/Ventures/Cedar/Cedar.md", "System/notes.md", "Wikis/Knowledge/wiki/standard.md"):
            self.assertIn(shown, said)

    def test_with_no_flags_known_nothing_of_a_zone_is_named(self):
        said = " ".join(re.sub(r"<[^>]+>", " ", block(self.LINES, shown={})).split())
        self.assertNotIn("Cedar.md", said)
        self.assertIn("System/notes.md", said)

    def test_a_mail_line_names_the_held_zone_only_when_it_is_open(self):
        for zone, named in (("Personal", False), ("Ventures", True)):
            markup = block([line(5, tool="mcp__fakemail__search", session="s1", source="fakemail", held_zone=zone)], shown={"walled": self.WALLED})
            self.assertEqual(named, ("held back from %s" % zone) in markup, zone)


class TestTheSection(unittest.TestCase):
    def test_it_names_the_guard_once_with_one_question_mark(self):
        markup = block([])
        shown = visible_text(markup)
        self.assertEqual(1, shown.count("Read guard"))
        tags = Tags(markup.replace('id="readguard-settings" hidden', 'id="readguard-settings"'))
        visible_buttons = [t for t in tags.out if t[0] == "button" and "qhelp" in (t[1].get("class") or "")
                           and not any("hidden" in a or (tg == "details") for tg, a in t[2])]
        self.assertEqual(1, len(visible_buttons))

    def test_one_sentence_says_what_it_protects(self):
        self.assertIn("The assistant does not read what sits behind the wall of another zone.", visible_text(block([])))      # #681

    def test_three_choices_each_with_its_consequence(self):
        markup = block([], mode="off")
        for value, name, said in (("off", "Off", "Nothing is checked when the assistant reads."),
                                  ("warn", "Watch", "Nothing is stopped. For a week, you see what would have been."),
                                  ("enforce", "On", "Reads behind another wall are stopped.")):
            self.assertRegex(markup, r'<input type="radio" name="rg-mode" value="%s"' % value)
            self.assertIn("<b>%s</b>" % name, markup)
            self.assertIn(said, markup)
        self.assertRegex(markup, r'<input type="radio" name="rg-mode" value="off" checked>')
        self.assertNotIn("Watch only", markup)

    def test_how_it_is_installed_is_behind_the_question_mark(self):
        markup = block([])
        self.assertIn(rgs.HELP_TEXT, re.search(r'id="help-readguard".*?</p>', markup, re.S).group(0))        # #681's text, behind the "?"
        self.assertNotIn(rgs.HELP_TEXT, visible_text(markup))

    def test_across_a_wall_is_on_the_page_only_under_on_with_a_line_for_each_choice(self):
        for mode, shown in (("off", False), ("warn", False), ("enforce", True)):
            markup = block([], mode=mode)
            self.assertEqual(shown, 'data-rg="cross"' in markup, mode)                # not drawn at all under Off and Watch (#683)
            self.assertEqual(shown, "Across a wall" in markup, mode)
            self.assertNotIn("Once you choose On", markup)
        on = block([], mode="enforce")
        self.assertIn("<b>Refuse</b><small>Every read across a wall is stopped.</small>", on)
        self.assertIn("<b>Ask me</b><small>You decide each time, for one session.</small>", on)
        self.assertRegex(on, r'name="rg-cross" value="deny" checked')

    def test_the_connected_services_are_in_a_closed_fold_named_for_them_under_watch_and_on(self):
        services = [{"name": "Gmail", "choice": "check", "patterns": ["mcp__*Gmail*"], "unmatched": False},
                    {"name": "Weather", "choice": "", "patterns": [], "unmatched": True}]
        for mode in ("warn", "enforce"):
            markup = block([], mode=mode, services=services)
            fold = re.search(r'<details class="rgadv rgsvcs"(?P<open>[^>]*)>(?P<body>.*?)</details>', markup, re.S)
            self.assertIsNotNone(fold, mode)
            self.assertNotIn(" open", fold.group("open"))
            self.assertIn('<span id="rg-services-name">Connected services (1 not decided)</span>', fold.group("body"))
            self.assertNotIn("Advanced", markup)
            self.assertNotRegex(markup, r"mcp__|\*")                                 # no pattern, no tool name, anywhere
        self.assertNotIn("rg-services", block([], mode="off", services=services))   # not on the page under Off
        self.assertNotIn("not decided", block([], mode="warn", services=services[:1]))

    def test_codex_keeps_its_one_line_in_place_of_the_services(self):
        state = dict(STATE, services=[{"name": "Gmail", "choice": "check", "patterns": ["mcp__*Gmail*"], "unmatched": False}])
        markup = rgs.guard_block(sg, state, True, button, text, "solo", OPEN)
        self.assertIn(sg.CODEX_LINE, markup)
        self.assertNotIn("rg-services", markup)


if __name__ == "__main__":
    unittest.main()

