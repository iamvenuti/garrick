"""Settings as one grid, and in plain words (#673, #675).

    cd tests && python3 -m unittest test_settings_layout

#673: every setting row is three columns, a label, a control and a "?", so the controls and the "?" buttons stand at one
place in every section. One size of checkbox and radio, one look for each kind of action, one size of text for hints, a
list of sections that names every section, a Notifications list with only switches in it, and an Open at login note that
speaks only once the app has answered. This file holds the markup and the style rules; where each pixel falls is measured
in a headless shell by the page gate, which no test here needs.

#675: the choices a business user meets say what they do, and the words of the fade tool and of the model (dormant, grade,
effort, How far it may go) stand in a label only with a line that explains them.
"""

from __future__ import annotations

import html as htmllib
import re
import sys
import unittest
from html.parser import HTMLParser

sys.dont_write_bytecode = True

from test_settings_ui import SettingsCase  # noqa: E402
from test_status import REPO, status  # noqa: E402
from test_view_settings import Fixtures  # noqa: E402

sys.path.insert(0, str(REPO / "extras" / "status"))
import settings_guard as sg  # noqa: E402
import settings_help as sh  # noqa: E402

VOID = ("input", "br", "img", "meta", "link", "hr")


class Dom(HTMLParser):
    """A small tree of the Settings markup: every element with its attributes, its children and its own text."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "a": {}, "kids": [], "text": "", "up": None}
        self.at = self.root
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "a": dict(attrs), "kids": [], "text": "", "up": self.at}
        self.at["kids"].append(node)
        if tag not in VOID:
            self.at = node

    def handle_endtag(self, tag):
        n = self.at
        while n is not None and n["tag"] != tag:
            n = n["up"]
        if n is not None and n["up"] is not None:
            self.at = n["up"]

    def handle_data(self, data):
        self.at["text"] += data

    def walk(self, node=None):
        node = node or self.root
        for k in node["kids"]:
            yield k
            yield from self.walk(k)

    def find(self, tag=None, cls=None, **attrs):
        for n in self.walk():
            if tag and n["tag"] != tag:
                continue
            if cls and cls not in (n["a"].get("class") or "").split():
                continue
            if any(n["a"].get(k.replace("_", "-")) != v for k, v in attrs.items()):
                continue
            yield n

    def text_of(self, node):
        return " ".join((node["text"] + " " + " ".join(self.text_of(k) for k in node["kids"])).split())


def classes(n):
    return (n["a"].get("class") or "").split()


class LayoutCase(Fixtures):
    def dom(self, rich=True):
        markup = self.rich() if rich else self.bare()
        return Dom(markup), markup


class TestOneGrid(LayoutCase):
    def test_every_setting_row_is_a_label_a_control_and_a_question_mark(self):
        dom, _ = self.dom()
        rows = [n for n in dom.walk() if "srow" in classes(n) and "launcher-row" in classes(n)]
        self.assertGreater(len(rows), 40)
        for row in rows:
            kids = [classes(k) for k in row["kids"]]
            self.assertEqual("slab", kids[0][0], row["a"])
            self.assertEqual("sctl", kids[1][0], row["a"])
            if len(kids) > 2:
                self.assertEqual(["qhelp"], kids[2], row["a"])          # the "?" stands last in its row, in its own column
            self.assertLessEqual(len(kids), 3)

    def test_the_control_cell_starts_with_the_control_so_it_starts_at_the_cell(self):
        dom, _ = self.dom()
        for row in (n for n in dom.walk() if "srow" in classes(n) and "launcher-row" in classes(n)):
            ctl = row["kids"][1]
            first = ctl["kids"][0] if ctl["kids"] else None
            if first is not None:
                self.assertIn(first["tag"], ("input", "select", "button", "span", "label", "a", "textarea"), first)

    def test_the_grid_has_one_control_column_and_one_help_column(self):
        css = status.SETTINGS_CSS
        self.assertRegex(css, r"dialog\.settings \.srow\{display:grid;grid-template-columns:minmax\(0,1fr\) var\(--sctl\) var\(--sq\)")
        self.assertIn("dialog.settings{--sctl:232px", css)
        self.assertRegex(css, r"\.srow>\.qhelp\{grid-column:3")
        self.assertRegex(css, r"\.srow>\.sctl\{grid-column:2")

    def test_the_gap_of_a_heading_is_the_gap_of_a_row(self):
        css = status.SETTINGS_CSS
        self.assertIn("--sgap:12px", css)
        self.assertIn("column-gap:var(--sgap)", css)
        self.assertIn("dialog.settings h3{gap:var(--sgap)}", css)

    def test_selects_fill_their_cell_so_those_of_a_section_are_one_width(self):
        css = status.SETTINGS_CSS
        self.assertRegex(css, r"\.srow>\.sctl>select[^{]*\{[^}]*width:100%")
        dom, _ = self.dom()
        for sel in dom.find("select"):
            if "hidden" in sel["a"]:
                continue                                                  # a colour picker's own list stays hidden
            cell = sel["up"]
            self.assertIn("sctl", classes(cell), sel["a"])

    def test_one_size_for_a_checkbox_and_one_for_a_radio_across_the_pane(self):
        css = status.SETTINGS_CSS + status.MEMORY_CSS + sg.CSS
        self.assertIn("dialog.settings input[type=checkbox],dialog.settings input[type=radio]{width:16px;height:16px", css)
        for name, rule in (("memory", status.MEMORY_CSS), ("guard", sg.CSS)):
            self.assertNotRegex(rule, r"input\[type=(checkbox|radio)\][^{]*\{[^}]*width", name)
        self.assertNotRegex(status.SETTINGS_CSS.replace("dialog.settings input[type=checkbox],dialog.settings input[type=radio]{width:16px;height:16px", ""),
                            r"input\[type=(checkbox|radio)\][^{]*\{[^}]*(width|height):1[0-5]px")

    def test_one_size_of_text_for_hints_and_status_lines(self):
        css = status.SETTINGS_CSS
        self.assertIn("dialog.settings .chnote,dialog.settings .hint,dialog.settings .muted{font-size:var(--fs-meta)}", css)

    def test_a_change_that_opens_a_dialog_is_a_button_in_every_section(self):
        dom, _ = self.dom()
        changes = [n for n in dom.walk() if n["tag"] in ("a", "button") and dom.text_of(n) == "Change\u2026"]
        self.assertGreaterEqual(len(changes), 3)                         # a zone's, another zone's, the machine's
        for n in changes:
            self.assertEqual("button", n["tag"])
            self.assertIn("sm", classes(n))

    def test_a_secondary_action_is_a_small_button_and_a_main_action_a_large_one(self):
        dom, _ = self.dom()
        for text in ("Review them", "Full list", "Set up Telegram", "Add", "Remove", "Show"):
            for n in dom.walk():
                if n["tag"] in ("a", "button") and dom.text_of(n) == text:
                    self.assertIn("sm", classes(n), text)
        for ident in ("rel-check", "graph-reset", "reset-view"):
            for n in dom.find(id=ident):
                self.assertIn("lg", classes(n), ident)

    def test_a_link_that_leaves_the_page_looks_like_a_link(self):
        dom, _ = self.dom()
        links = {dom.text_of(n): n for n in dom.find("a", cls="setlink")}
        self.assertEqual({"Report a bug", "Suggest a change", "Release notes"}, set(links))
        self.assertIn("a.setlink", status.SETTINGS_CSS)
        self.assertRegex(status.SETTINGS_CSS, r"a\.setlink[^{]*\{[^}]*text-decoration:underline")


class TestTheListOfSections(LayoutCase):
    SEVEN = ["Opening work", "Ask", "Notifications", "Older pages", "Walls", "Look", "About"]

    def test_seven_sections_seven_entries_and_no_group_heading_with_the_graph_on_or_off(self):
        for graph in (True, False):
            with self.subTest(graph=graph):
                args = list(self.args())
                args[4] = graph
                markup = status.settings(*args)
                dom = Dom(markup)
                entries = [(a["a"]["data-setgo"], dom.text_of(a)) for a in dom.find("a") if "data-setgo" in a["a"]]
                sections = [n for n in dom.find("section", cls="setsec")]
                self.assertEqual(self.SEVEN, [t for _, t in entries])
                self.assertEqual([i for i, _ in entries], [n["a"]["id"] for n in sections])
                self.assertEqual([i for i, _ in status.SET_SECTIONS], [n["a"]["id"] for n in sections])
                for gone in ("setgroup", "setgrp", "setnavgrp", "setnavh"):
                    self.assertNotIn(gone, markup)

    def test_the_read_guard_ask_telegram_and_what_waits_are_parts_with_no_entry(self):
        _, markup = self.dom()
        dom = Dom(markup)
        entries = {a["a"]["data-setgo"] for a in dom.find("a") if "data-setgo" in a["a"]}
        for ident in ("readguard-settings", "channels-ask", "channels-telegram", "menu-settings", "askbox-settings",
                      "zone-settings", "machine-settings", "preview-settings", "graph-colour-settings"):
            self.assertIn('id="%s"' % ident, markup, ident)
            self.assertNotIn(ident, entries)
        self.assertNotIn('id="channels-held"', markup)                    # nothing waits in the fixture
        ask = self.section(markup, "ask-settings")
        self.assertLess(ask.index('id="askbox-settings"'), ask.index('id="channels-ask"'))     # the Ask box rows first
        self.assertIn('<h4 class="setsubh">Telegram<button class="qhelp"', ask)
        self.assertNotIn("<h3>Telegram", markup)

    def test_the_highlight_follows_the_heading_nearest_the_top(self):
        self.assertIn("var h=s.querySelector('h3')||s;if(h.getBoundingClientRect().top<=top)cur=s", status.JS)
        self.assertIn("getBoundingClientRect().top+36", status.JS)


class TestOldLinksLand(LayoutCase):
    """#682: every anchor that opened Settings at a section in 0.79.0 opens the section that holds those rows now."""

    OLD = ("launcher-settings", "follow-settings", "zone-settings", "graph-colour-settings", "menu-settings", "notify-settings",
           "channels-settings", "channels-ask", "channels-telegram", "channels-held", "memory-settings", "walls-settings",
           "readguard-settings", "machine-settings", "about-settings", "preview-settings")

    def test_every_old_section_and_every_anchor_the_page_and_the_app_send_is_in_the_table(self):
        sections = {k for k, _ in status.SET_SECTIONS}
        self.assertEqual(sections, set(status.SET_ANCHORS.values()))
        for old in self.OLD:
            self.assertIn(old, status.SET_ANCHORS)
        _, markup = self.dom()
        ids = set(re.findall(r'\bid="([a-z-]+-settings)"', markup.split("</nav>", 1)[1])) - {"close-settings"}
        sources = [status.__file__, str(REPO / "extras" / "status" / "page_action.py")] + \
                  [str(f) for f in (REPO / "extras" / "status" / "app").glob("*.swift")] + \
                  [str(f) for f in (REPO / "extras" / "status").glob("settings_*.py")]
        said = set()
        for src in sources:
            said |= set(re.findall(r"#?([a-z][a-z-]*-settings)\b", open(src, encoding="utf-8").read()))
        for anchor in said & (ids | set(self.OLD)):
            self.assertIn(anchor, status.SET_ANCHORS, anchor)
        for anchor in ids:
            self.assertIn(anchor, status.SET_ANCHORS, anchor)

    def test_each_anchor_is_inside_the_section_it_maps_to(self):
        _, markup = self.dom()
        for anchor, sec in status.SET_ANCHORS.items():
            if 'id="%s"' % anchor not in markup:
                continue                                    # a part this workspace does not have (nothing waits, say)
            with self.subTest(anchor=anchor):
                self.assertIn('id="%s"' % anchor, self.section(markup, sec))
        for anchor in ("zone-settings", "menu-settings", "machine-settings"):     # the acceptance's three
            self.assertIn('id="%s"' % anchor, markup)

    def test_the_script_opens_the_section_scrolls_to_the_rows_and_focuses_the_heading(self):
        js = status.JS
        self.assertIn('<script type="application/json" id="settings-anchors">', self.bare())
        self.assertIn("snAt=JSON.parse(document.getElementById('settings-anchors').textContent)", js)
        self.assertIn("window.StatusSettings={open:function(at){var f=snFind(at);", js)
        self.assertIn("if(t.tagName==='DETAILS')t.open=true;", js)               # a fold that holds the rows opens
        self.assertIn("s.focus({preventScroll:true})", js[js.index("function snGo("):])
        self.assertIn("closest('[data-setopen],a[href^=\"#\"]')", js)            # a link or button elsewhere on the page
        self.assertIn("if(snFind(location.hash))", js)
        self.assertIn("document.getElementById('open-settings').onclick=function(){window.StatusSettings.open()};", js)


class TestInTheBrowser(LayoutCase):
    """#682: in a browser the rows that need the app are not shown, and no section is left with a heading and no row."""

    def test_every_section_a_browser_shows_has_a_row_a_browser_shows(self):
        for name in ("bare", "rich"):
            dom = Dom(getattr(self, name)())
            for sec in dom.find("section", cls="setsec"):
                if "apponly" in classes(sec) or "hidden" in sec["a"]:
                    continue                                 # the whole section is the app's: a browser shows no heading
                shown = []
                stack = [(k, False) for k in sec["kids"]]
                while stack:
                    n, off = stack.pop()
                    off = off or "apponly" in classes(n) or "hidden" in n["a"] or "display:none" in (n["a"].get("style") or "")
                    if "srow" in classes(n) and "launcher-row" in classes(n) and not off:
                        shown.append(n)
                    stack.extend((k, off) for k in n["kids"])
                with self.subTest(fixture=name, section=sec["a"]["id"]):
                    self.assertTrue(shown)

    def test_opening_work_shows_the_cards_rows_and_not_the_menu_rows(self):
        markup = self.bare()
        sec = self.section(markup, "launcher-settings")
        self.assertRegex(sec, r'<div class="setpart menuset apponly" id="menu-settings" hidden>')
        self.assertLess(sec.index('data-launcher="note"'), sec.index('id="menu-settings"'))
        for ident in ("menu-show", "menu-login", "menu-hotkey", "menu-finder"):
            self.assertIn('id="%s"' % ident, sec.split('id="menu-settings"')[1])


class TestEveryControlStays(LayoutCase):
    """#682: every control Settings had in 0.79.0 is still on the page, with the id or data- attribute the page's script reads
    to save it, so each saves the same key with the same value. The Ask box's rows are all in Ask."""

    IDS = ("launch-note", "launch-preview", "launch-finder", "launch-cmux", "launch-codex", "launch-claude", "desk-agent",
           "graph-follow", "graph-reset", "menu-show", "menu-style", "menu-login", "menu-hotkey", "menu-finder", "menu-ask",
           "menu-askkey", "menu-askclose-esc", "menu-askclose-click", "menu-dictation", "menu-dictkey", "n-after", "n-quiet",
           "n-from", "n-to", "ch-ask-tier", "ch-ask-effort", "ch-ask-autonomy", "ch-telegram-tier", "ch-telegram-effort",
           "ch-telegram-autonomy", "m-wake", "m-reach", "m-night", "m-min", "role-change", "rel-check", "rel-on", "rel-every",
           "usage-on", "reset-view")
    ATTRS = ('data-nt="needs-you"', 'data-nt="finished"', 'data-nt="job-failed"', 'data-nt="release"', 'data-mwikion="Meetings"',
             'data-mk="dormant"', 'data-mk="archived"', 'data-mk="never"', 'data-mk="types"', 'data-mk="domains"', 'data-mpin="thread"',
             'data-mpin="project"', 'data-mpin="todo"', 'data-mpin="pinned"', 'name="rg-mode"', 'name="rg-cross"', 'data-rg-add="tools"',
             'data-rg-add="skip"', 'class="act sm wchange"', 'class="zcol"', 'class="zico"', 'name="garrick-default"')

    def test_every_control_is_still_there(self):
        self.rich()
        self.role("solo")                                       # a laptop copy shows one line in place of the read guard's rows
        markup = self.draw()
        for ident in self.IDS:
            self.assertIn('id="%s"' % ident, markup, ident)
        for attr in self.ATTRS:
            self.assertIn(attr, markup, attr)

    def test_every_row_about_the_ask_box_is_in_ask_and_none_in_opening_work(self):
        markup = self.rich()
        ask, opening = self.section(markup, "ask-settings"), self.section(markup, "launcher-settings")
        for ident in ("menu-ask", "menu-askkey", "menu-askclose-esc", "menu-askclose-click", "menu-dictation", "menu-dictkey",
                      "ch-ask-tier", "ch-ask-effort", "ch-ask-autonomy", "ch-telegram-tier"):
            self.assertIn('id="%s"' % ident, ask, ident)
            self.assertNotIn('id="%s"' % ident, opening, ident)


class TestOneRowForEachApp(LayoutCase):
    def test_the_four_old_names_are_not_on_the_page(self):
        """#682: one row for Claude and one for Codex, so none of 0.79.0's four names is on the page, script included."""
        html = self.page(launchers=("finder", "cmux", "codex", "claude"))
        for gone in ("Open in Claude", "New session in Claude", "Open in Codex", "New session in Codex"):
            self.assertNotIn(gone, html)
        dialog = self.section(html, "launcher-settings")
        self.assertEqual(1, dialog.count('data-launcher="claude"'))
        self.assertEqual(1, dialog.count('data-launcher="codex"'))


class TestNotifications(LayoutCase):
    def test_the_list_holds_switches_only_and_a_summary_a_job_sends_moves_under_it_as_one_line(self):
        dom, markup = self.dom()                                            # the rich fixture: the todo sweep sends its own notice
        sec = next(dom.find("section", id="notify-settings"))
        rows = [n for n in dom.walk() if "nsitem" in classes(n)]
        shown = [r for r in rows if any(k["tag"] == "input" and k["a"].get("type") == "checkbox" for c in r["kids"] for k in [c] + c["kids"])]
        self.assertEqual(len(rows), len(shown))
        self.assertNotIn("nsown", markup.split('id="notify-settings"')[1].split("</section>")[0].replace('class="chnote nsown"', ""))
        self.assertEqual(1, len(list(dom.find("p", id="n-own"))))
        said = dom.text_of(next(dom.find("p", id="n-own")))
        self.assertEqual("The morning summaries are set by your assistant. Ask it to change them.", said)     # #681
        self.assertEqual("todo-summary", next(dom.find("input", data_nt="todo-summary"))["a"]["data-nt"])      # kept, out of sight
        self.assertIn("hidden", next(dom.find("input", data_nt="todo-summary"))["a"])

    def test_with_no_job_of_its_own_every_notice_has_its_switch_and_there_is_no_line(self):
        dom, _ = self.dom(rich=False)
        self.assertEqual([], list(dom.find("p", id="n-own")))
        self.assertGreaterEqual(len(list(dom.find("input", type="checkbox", data_nt="todo-summary"))), 1)

    def test_quiet_hours_stand_in_the_same_columns(self):
        dom, _ = self.dom()
        row = next(dom.find("div", cls="nsq"))
        self.assertIn("srow", classes(row))
        self.assertEqual("n-quiet", row["kids"][1]["kids"][0]["a"].get("id"))


class TestOpenAtLogin(unittest.TestCase):
    def test_the_note_says_nothing_of_macos_until_the_app_has_answered(self):
        js = status.MENU_SETTINGS_JS
        self.assertIn("window.GarrickApp&&a.login==null", js)
        self.assertNotIn("if(a.login==null)document.getElementById('menu-login-note').textContent='Needs macOS 13 or later'", js)
        self.assertIn("a.said&&a.said.login", js)                           # the reason, only when the app gives one

    def test_before_an_answer_the_row_holds_its_own_line(self):
        self.assertEqual("With the window as you left it.", status.MENU_LOGIN)      # #681
        self.assertIn(status.MENU_LOGIN, status.menu_settings())


class TestPlainWords(LayoutCase):
    def test_each_choice_of_how_far_it_may_go_has_its_line_in_the_page_and_in_the_help(self):
        dom, markup = self.dom()
        ask = Dom(markup.split('id="channels-ask"')[1].split("</section>")[0])
        said = " ".join(ask.text_of(n) for n in ask.find("ul", cls="chlevels"))
        for phrase in ("answers from your workspace, changes nothing", "may also make changes you would make by hand, and asks before anything is sent, shared or deleted",
                       "as Act, and also sends what you asked for without asking you first", "Read", "Act", "Full"):
            self.assertIn(phrase, said)
        tg = Dom(markup.split('id="channels-telegram"')[1].split("</section>")[0])
        said_tg = " ".join(tg.text_of(n) for n in tg.find("ul", cls="chlevels"))
        self.assertIn("Read", said_tg)
        self.assertIn("Act", said_tg)
        self.assertNotIn("Full", said_tg)                                   # Telegram never offers it
        text = " ".join(t for pat, k, n, t in sh.ROWS if k == "ch-autonomy")
        self.assertEqual("Start with Read. Choose Act when you trust the answers.", text)     # the choices carry their lines (#681)

    def test_model_size_and_effort_have_one_line_between_them(self):
        _, markup = self.dom()
        ask = markup.split('id="channels-ask"')[1].split("</section>")[0]
        self.assertEqual(1, ask.count('data-for="ask-size"'))
        self.assertIn("Larger and more effort: fuller answers, slower, and they cost more.", ask)       # #681
        text = " ".join(t for pat, k, n, t in sh.ROWS if k == "ch-tier")
        self.assertIn("deep:", text)

    def test_older_material_says_what_the_user_sees(self):
        _, markup = self.dom()
        sec = markup.split('id="memory-settings"')[1].split("</section>")[0]
        for phrase in ("Dormant after", "Archived after", "Never archive", "page would move", "Review them", "let old pages become dormant",
                       "You pinned it", "Suggest bringing a page back when new work links to it"):     # #681's words
            self.assertIn(phrase, sec)
        self.assertNotIn("would change grade", sec)
        seen = htmllib.unescape(re.sub(r"<[^>]+>", " ", sec.replace("<ROOT>", "ROOT")))   # the words shown
        for old in ("Out of everyday answers after", "Kept only in the archive after", "fade", "pinned: true", "digest"):
            self.assertNotIn(old, seen)
        self.assertNotIn("never archived</label>", sec)

    def test_the_count_line_in_the_page_and_in_the_script_say_it_the_same_way(self):
        c = {"working": 600, "dormant": 17, "to_dormant": 5, "to_archive": 7}
        self.assertEqual("Meetings: 600 working · 17 dormant. 12 pages would move.", status.memory_said("Meetings", c))
        self.assertEqual("Meetings: 3 working · 0 dormant. 1 page would move.", status.memory_said("Meetings", {"working": 3, "to_dormant": 1}))
        self.assertEqual("Meetings: 3 working · 0 dormant. No page would move.", status.memory_said("Meetings", {"working": 3}))
        self.assertIn("' page'+(mv===1?'':'s')+' would move.'", status.MEMORY_JS)
        self.assertIn("No page would move.", status.MEMORY_JS)

    def test_preview_features_are_a_closed_fold_at_the_end_of_about_with_one_line(self):
        _, markup = self.dom()
        about = self.section(markup, "about-settings")
        fold = self.section(markup, "preview-settings")
        self.assertTrue(about.endswith(fold + "</section>"))
        self.assertTrue(fold.startswith('<details class="setfold" id="preview-settings"><summary>Preview features</summary>'))
        self.assertIn("Not released yet. Ask your assistant to switch one on.", fold)
        self.assertNotIn(" open", fold[:fold.index(">")])                 # closed when Settings opens
        self.assertNotIn("garrick-flags.json", fold)                           # the docs page names it (#681, #682)
        self.assertNotIn("qhelp", fold)

    def test_graph_colours_are_a_closed_fold_in_look(self):
        _, markup = self.dom()
        look = self.section(markup, "look-settings")
        fold = self.section(markup, "graph-colour-settings")
        self.assertIn(fold, look)
        self.assertTrue(fold.startswith('<details class="setfold apponly" id="graph-colour-settings"><summary>Graph colours</summary>'))
        self.assertIn('id="graph-reset"', fold)

    def test_opening_a_thread_has_a_head_over_the_radio_column_and_reset_view_says_what_it_resets(self):
        _, markup = self.dom()
        sec = self.section(markup, "launcher-settings")
        self.assertIn('<span class="shcol">Default</span>', sec)
        look = self.section(markup, "look-settings")
        self.assertIn("Shows every card again, in its first place.", look.split('id="view-settings"')[1])
        tail = look.split('id="view-settings"')[1]                          # Reset view is the last row of Look
        self.assertNotRegex(tail, r'class="(setpart|setfold|launcher-row srow (?!>))')
        self.assertEqual(1, tail.count("launcher-row srow"))


    def test_a_word_that_needs_a_meaning_gets_it_behind_a_question_mark(self):
        """#681 in place of #675's rule: dormant, effort and How far it may go are given their meaning behind a "?" or by the
        choices' own lines, not by a line under every label."""
        _, markup = self.dom()
        self.assertIn("A dormant page is used only when a search reaches back.", markup)
        self.assertIn("Larger and more effort: fuller answers, slower, and they cost more.", markup)
        self.assertIn('class="chlevels"', markup)


if __name__ == "__main__":
    unittest.main()
