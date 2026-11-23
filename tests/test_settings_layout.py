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

    def test_every_setting_row_has_its_question_mark_unless_it_is_the_head_of_a_column(self):
        dom, _ = self.dom()
        bare = [dom.text_of(n)[:50] for n in dom.walk() if "srow" in classes(n) and "launcher-row" in classes(n)
                and not any("qhelp" in classes(k) for k in n["kids"])]
        # a row the help table does not know is a row without one: the table names them, and these are all that is left
        self.assertEqual([], [b for b in bare if not re.match(r"(Out of everyday|Kept only|Never archive|Page domains|Look for|Reset view|Close the Ask|Without being asked|Answers)", b)], bare)    # Answers: its "?" text comes with #681

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
    def test_every_section_with_a_heading_has_an_entry_and_the_group_names_fit_one_line(self):
        dom, markup = self.dom()
        entries = {a["a"]["data-setgo"] for a in dom.find("a") if "data-setgo" in a["a"]}
        sections = [n for n in dom.find("section", cls="setsec") if any(k["tag"] == "h3" for k in n["kids"])]
        self.assertGreaterEqual(len(sections), 16)
        self.assertEqual([], [n["a"]["id"] for n in sections if n["a"]["id"] not in entries])
        for key, title in status.SET_GROUPS:
            self.assertLessEqual(len(title), 18, title)

    def test_the_read_guard_ask_telegram_and_what_waits_are_sections_of_their_own(self):
        dom, _ = self.dom()
        ids = {n["a"].get("id") for n in dom.find("section")}
        for ident in ("readguard-settings", "channels-ask", "channels-telegram", "channels-held"):
            self.assertIn(ident, ids)

    def test_the_highlight_follows_the_heading_nearest_the_top(self):
        self.assertIn("var h=s.querySelector('h3')||s;if(h.getBoundingClientRect().top<=top)cur=s", status.JS)
        self.assertIn("getBoundingClientRect().top+36", status.JS)


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
        self.assertIn("The morning Todo summary is ready", said)
        self.assertIn("Sent by the todo sweep to the command you set", said)
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
        self.assertIn("Starts the app when you log in", status.MENU_LOGIN)
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
        helps = {k: t for _, k, _, t in sh.ROWS}
        text = " ".join(t for pat, k, n, t in sh.ROWS if k == "ch-ask-autonomy")
        for part in ("answers from your workspace and changes nothing", "asks before anything is sent, shared or deleted", "without asking you first"):
            self.assertIn(part, text)

    def test_answers_takes_the_place_of_model_size_and_effort_with_no_note(self):
        _, markup = self.dom()
        ask = markup.split('id="channels-ask"')[1].split("</section>")[0]
        self.assertEqual(0, ask.count('data-for="ask-size"'))                               # the note goes (#683)
        self.assertIn('data-answers="ask"', ask)
        for gone in ("Model size", "Effort", "A larger size and more effort"):
            self.assertNotIn(gone, ask)

    def test_older_material_says_what_the_user_sees(self):
        _, markup = self.dom()
        sec = markup.split('id="memory-settings"')[1].split("</section>")[0]
        for phrase in ("Out of everyday answers after", "Kept only in the archive after", "Never archive", "page would move", "Review them"):
            self.assertIn(phrase, sec)
        self.assertNotIn("would change grade", sec)
        self.assertNotIn("dormant after", sec)
        self.assertNotIn("archived after", sec)
        self.assertNotIn("never archived</label>", sec)

    def test_the_count_line_in_the_page_and_in_the_script_say_it_the_same_way(self):
        c = {"working": 600, "dormant": 17, "to_dormant": 5, "to_archive": 7}
        self.assertEqual("Meetings: 600 working · 17 dormant. 12 pages would move.", status.memory_said("Meetings", c))
        self.assertEqual("Meetings: 3 working · 0 dormant. 1 page would move.", status.memory_said("Meetings", {"working": 3, "to_dormant": 1}))
        self.assertEqual("Meetings: 3 working · 0 dormant. No page would move.", status.memory_said("Meetings", {"working": 3}))
        self.assertIn("' page'+(mv===1?'':'s')+' would move.'", status.MEMORY_JS)
        self.assertIn("No page would move.", status.MEMORY_JS)

    def test_preview_features_say_how_to_switch_one_on_and_name_the_file_behind_the_question_mark(self):
        _, markup = self.dom()
        sec = markup.split('id="preview-settings"')[1].split("</section>")[0]
        visible = re.sub(r'<p class="hint sethelp".*?</p>', "", sec, flags=re.S)
        self.assertIn("Off until you ask your assistant to switch one on.", visible)
        self.assertNotIn("garrick-flags.json", re.sub(r'title="[^"]*"', "", visible))
        self.assertIn("System/garrick-flags.json", sec)                        # behind the "?"
        self.assertIn("ask your assistant to switch one on", re.search(r'id="help-preview".*?</p>', sec, re.S).group(0))

    def test_opening_a_thread_has_a_head_over_the_radio_column_and_reset_view_says_what_it_resets(self):
        _, markup = self.dom()
        sec = markup.split('id="launcher-settings"')[1].split("</section>")[0]
        self.assertIn('<span class="shcol">Click a name to</span>', sec)
        self.assertIn("Show every card again, in its first place", markup.split('class="setfoot"')[1])

    def test_a_word_of_the_tools_stands_in_a_label_only_with_a_line_that_explains_it(self):
        """dormant, grade, effort and How far it may go: in a label only where the row, or the section's own line, explains it."""
        banned = ("dormant", "grade", "effort", "how far it may go")
        for name in ("rich", "bare"):
            markup = getattr(self, name)()
            dom = Dom(markup)
            for section in dom.find("section", cls="setsec"):
                lede = " ".join(dom.text_of(p) for p in section["kids"] if "setlede" in classes(p)).lower()
                stack = list(section["kids"])
                while stack:
                    n = stack.pop()
                    stack.extend(n["kids"])
                    if "sethelp" in classes(n) or n["tag"] in ("script", "style", "option", "textarea"):
                        continue
                    labels = []
                    if n["tag"] in ("label", "h3", "h4", "button", "legend", "summary") or "slab" in classes(n):
                        labels.append(dom.text_of(n))
                    for text in labels:
                        for word in banned:
                            if word in text.lower() and "explains" not in text.lower():
                                row = n
                                while row is not None and "srow" not in classes(row):
                                    row = row["up"]
                                row_text = dom.text_of(row).lower() if row is not None else ""
                                after = ""
                                if row is not None and row["up"] is not None:
                                    sib = row["up"]["kids"]
                                    at = sib.index(row)
                                    nxt = [dom.text_of(s).lower() for s in sib[at + 1:at + 5] if "sethelp" not in classes(s) and (classes(s) or [""])[0] in ("schint", "chlevels")]
                                    after = " ".join(nxt[:2])
                                explained = (lede and word in lede) or len(row_text) > len(text) + 12 or (after and len(after) > 20)
                                self.assertTrue(explained, "%s: %r has no line that explains it (%s)" % (name, text, section["a"].get("id")))


if __name__ == "__main__":
    unittest.main()
