#!/usr/bin/env python3
"""settings_help.py: a "?" on every setting row of Settings, in plain words (#621).

Each Settings section has one "?" for the section. A choice such as *Refuse* or *Ask me* needs its own explanation,
next to it. status.py builds each section's rows as it always did; `with_row_help()` then finds each row of a section,
gives it a "?" built by status.py's own help_button(), and puts its text, made by help_text(), under it, hidden until the
"?" is pressed. The button stands at the end of its row, inside a label too: a button in a label does not toggle its box.

The rules every text keeps, and a test holds:

- It says what happens to the user, not how it is built: no file, no setting's name, no command, no issue number.
- It is short enough to read in one look, about 60 words at most.
- Where there are choices, it says when to pick each one.

A row the table below does not know is left as it was, and a test names it, so a row added later cannot go without one.
Standard library only.
"""

from __future__ import annotations

import html as _html
import re
from typing import Callable, Dict, List, Optional, Tuple

# The class of each kind of row: an element with one of these, holding a control, is a setting row.
ROW_CLASSES = ("launcher-row", "zrow", "gkrow", "wallrow", "mkind", "mlists", "mpin", "setrelrow", "nsitem", "nsq", "rgrow")
CONTROL = re.compile(r"<(?:input|select|textarea)\b|<button\b[^>]*class=\"act\"|class=\"(?:zbtn|wchange|rgchoice)\"|data-rolechange")
OPEN = re.compile(r'<(div|li|label|p)\b([^>]*)>')

# (a pattern found in the row's own markup, the key, the row's name, its text), the first that matches wins. The text is
# plain: `&` and quotes are escaped when it is put on the page.
ROWS: List[Tuple[str, str, str, str]] = [
    # Opening a thread
    (r'data-launcher="note"', "launch-note", "Open the note",
     "Adds Open the note to every project and thread card: it opens the thread's note in the app your Mac uses for notes. "
     "Leave it on unless you never open notes from here. Default makes a click on a thread's name do it."),
    (r'data-launcher="preview"', "launch-preview", "Preview",
     "Lets Explore show a note's text over the graph. It opens nothing. Leave it on to read a note without leaving the page. "
     "Switch it off if the graph feels crowded."),
    (r'data-launcher="finder"', "launch-finder", "Reveal in Finder",
     "Adds Reveal in Finder to the cards. Pick it when you also move files by hand. "
     "Default makes a click on a thread's name show its folder."),
    (r'data-launcher="cmux"', "launch-cmux", "Open in cmux",
     "Adds Open in cmux to the cards. It opens the thread in a cmux tab, one tab for each thread. Pick it if you work in cmux. "
     "Default makes a click on a thread's name do it."),
    (r'id="desk-agent"', "launch-desk-agent", "A cmux tab starts",
     "Which assistant a new cmux tab starts: Claude Code or Codex. Pick the one you work with. A tab that is already open keeps "
     "the one it has."),
    (r'data-launcher="codex"', "launch-codex", "Open in Codex",
     "Adds Open in Codex to the cards. It opens the project's folder in the Codex app. Pick it if you work in Codex. "
     "Default makes a click on a thread's name do it."),
    (r'data-launcher="claude"', "launch-claude", "Open in Claude",
     "Adds Open in Claude to the cards. It opens the project's folder in the Claude app. Pick it if you work in Claude. "
     "Default makes a click on a thread's name do it."),
    # Explore
    (r'id="graph-follow"', "follow", "Follow the zone in view",
     "On, the graph switches to the zone you are reading on the Threads card. Off, it stays on the zone you chose. "
     "Turn it off if the graph moving about distracts you."),
    # Menu bar
    (r'id="menu-show"', "menu-show", "Show the menu",
     "Shows a menu of your live projects outside this window, so one click from any app opens a project. Turn it on if you "
     "move between apps all day. Off keeps everything in this window."),
    (r'id="menu-style"', "menu-style", "Shows as",
     "Where the menu shows: as an icon in the menu bar, or as a panel that opens at the edge of the screen. Pick the icon if "
     "you want it quiet, a panel if you want it large."),
    (r'id="menu-login"', "menu-login", "Open at login",
     "Starts Garrick when you log in to this Mac, with the window as you left it. Turn it on if you use Garrick every day."),
    (r'id="menu-hotkey"', "menu-hotkey", "Hotkey",
     "A key combination that opens the menu or the panel from any app. Click the box and press the keys. "
     "Clear takes the key away."),
    (r'id="menu-ask"', "menu-ask", "Answer in the Ask box",
     "Lets the Ask box answer from your records. It keeps an assistant session ready, which spends model calls. Turn it off to "
     "stop that: the panel's field then opens your assistant instead."),
    (r'id="menu-askkey"', "menu-askkey", "Ask hotkey",
     "A key combination that opens the Ask box from any app. Click the box and press the keys. Clear takes the key away."),
    (r'id="menu-askclose-esc"', "menu-askclose", "Close the Ask box with",
     "How the Ask box closes: the Escape key, a click outside it, or both. One way always stays on, so the box can always "
     "be closed."),
    (r'id="menu-dictation"', "menu-dictation", "Then start dictation",
     "Starts dictation as the Ask box opens, so you can speak your question. Pick macOS Dictation, a press of Fn, or your own "
     "tool's shortcut. Pick Off if you type."),
    (r'id="menu-dictkey"', "menu-dictkey", "Dictation shortcut",
     "The shortcut your own dictation tool starts on. Click the box and press it. Pause the tool first if it takes the keys."),
    (r'id="menu-finder"', "menu-finder", "Finder menu",
     "Adds Garrick to Finder's right-click menu on a project or thread folder. macOS asks you to switch it on in System "
     "Settings, and this button opens that place. Pick it if you often start from Finder."),
    # Notifications
    (r'data-nt="needs-you"', "nt-needs-you", "A session needs me",
     "A notice when a session waits for you: a permission, a question or an approval. It is sent once for each wait. Turn it "
     "on if you leave sessions running while you work on something else."),
    (r'data-nt="finished"', "nt-finished", "A long task finishes",
     "A notice when a task that ran for at least the minutes you set is done. Raise the minutes to hear only about long ones."),
    (r'data-nt="todo-summary"', "nt-todo", "The morning Todo summary",
     "The morning notice with how many open actions each zone has. Turn it off if you read your lists on the page instead."),
    (r'data-nt="context-summary"', "nt-context", "The morning Context summary",
     "The morning notice with what the night's check fixed and what waits for you. Turn it off if you look at the Context "
     "card each day anyway."),
    (r'data-nt="job-failed"', "nt-job", "A scheduled job fails or recovers",
     "A notice when a scheduled job fails or works again. Turn it on if you rely on the nightly jobs and want to hear when "
     "one stops."),
    (r'data-nt="release"', "nt-release", "A newer Garrick is out",
     "A notice, once for each release, when a newer Garrick is out. It works only when the check for updates in About Garrick "
     "is on."),
    (r'id="n-quiet"', "nt-quiet", "Quiet hours",
     "Holds notices between the two times you set, and sends them in the morning. At night only a session that needs you "
     "gets through. Change the hours to fit your day."),
    # Channels
    (r'id="ch-ask-tier"', "ch-ask-tier", "Ask: model size",
     "How large a model answers in the Ask box. Small is quick and cheap. Large thinks longer and costs more. Pick Medium "
     "until an answer falls short."),
    (r'id="ch-ask-effort"', "ch-ask-effort", "Ask: effort",
     "How much thought goes into an answer. Low is faster. High takes longer and may answer better. Raise it for hard questions."),
    (r'id="ch-ask-autonomy"', "ch-ask-autonomy", "Ask: how far it may go",
     "Read only answers. Act also makes changes that can be undone, and asks you before anything is sent, shared or deleted. "
     "Full sends without asking you first. Pick Read until you trust it with more."),
    (r'id="ch-telegram-tier"', "ch-telegram-tier", "Telegram: model size",
     "How large a model answers in a Telegram chat. Small is quick and cheap. Large thinks longer and costs more. Pick Medium "
     "until an answer falls short."),
    (r'id="ch-telegram-effort"', "ch-telegram-effort", "Telegram: effort",
     "How much thought goes into an answer in a Telegram chat. Low is faster. High takes longer and may answer better."),
    (r'id="ch-telegram-autonomy"', "ch-telegram-autonomy", "Telegram: how far it may go",
     "Read only answers. Act also makes changes that can be undone, and asks you before anything is sent, shared or deleted. "
     "Telegram never offers Full. Pick Read until you trust it with more."),
    # Manage older material
    (r'data-mwikion="', "mem-wiki-%(wiki)s", "Let old pages become dormant",
     "Lets old pages of this wiki become dormant, then archived, so search stays on what matters. Turn it off to keep every "
     "page working. Nothing is deleted either way."),
    (r'class="mkind"', "mem-kind-%(kind)s", "Months for this kind of page",
     "How many months a page of this kind stays working before it goes dormant, and before it is archived. Tick never archived "
     "to let it go dormant and no further. Nothing is deleted."),
    (r'class="mlists"', "mem-lists-%(kind)s", "Which pages belong to this kind",
     "Which pages count as this kind: by page type or by domain, separated by commas. Change them only if a page ends up in "
     "the wrong kind."),
    (r'data-mpin="thread"', "mem-pin-thread", "A live thread links it",
     "A page that a live thread links stays working, however old. Leave it on unless old pages stay working that you "
     "would rather let go."),
    (r'data-mpin="project"', "mem-pin-project", "A live project's notes link it",
     "A page that the notes of a live project link stays working, however old. Leave it on unless you want such pages to age."),
    (r'data-mpin="todo"', "mem-pin-todo", "An open action links it",
     "A page that an open action in a Todo list links stays working, however old. Leave it on so a page you still need "
     "never goes dormant."),
    (r'data-mpin="pinned"', "mem-pin-pinned", "It says pinned",
     "A page that says it is pinned stays working, however old. This is how you keep one page by hand."),
    (r'id="m-wake"', "mem-wake", "Propose bringing a page back",
     "When on, a dormant page that active work links again is proposed for coming back. Off, only a page marked as pinned "
     "comes back."),
    (r'id="m-reach"', "mem-reach", "How far search reaches",
     "How far search reaches when you do not say. Working pages only is quicker and quieter. Working and dormant pages also "
     "looks at older ones: pick it if you often look for old material."),
    (r'id="m-night"', "mem-night", "Say it in the morning digest",
     "Adds a line to the morning digest when enough pages would change grade. Turn it off if you do not read the digest."),
    # Walls
    (r'class="wallrow"', "wall-%(zone)s", "Walled or open",
     "Walled keeps this zone's material in the zone. Open lets it go anywhere. Change asks your assistant to make the switch, "
     "and it asks you first."),
    # Zones, graph colours
    (r'class="zrow"', "zone-%(zone)s", "A zone's colour and icon",
     "A colour and an icon for this zone. They mark its name on every card, so you can tell zones apart at a glance. "
     "Choose none to leave the zone plain."),
    (r'class="gkrow"', "kind-%(kind)s", "A kind of note's colour",
     "The colour of this kind of note in Explore's graph. Pick one that stands out from its neighbours, or leave it on its "
     "default. Reset colours puts every kind back."),
    # About
    (r'id="rel-check"', "rel-check", "Check for updates",
     "Looks now at Garrick's public release page to see whether a newer version is out, and shows the answer here. Nothing "
     "about your work is sent. Press it when you want to know today, without waiting for the automatic check."),
    (r'id="rel-on"', "rel-on", "Check for a newer Garrick",
     "Looks once in a while at Garrick's public release page to see whether a newer version is out, and tells you. Nothing "
     "about your work is sent. Turn it on if you want to hear about updates."),
    (r'id="usage-on"', "usage-on", "Count which cards I open",
     "Keeps a count of which cards you open, and on which day, on this Mac only. Nothing else is kept: no name, no note, no "
     "text, and nothing is sent anywhere. It helps decide which cards are worth their space. Turn it off and nothing is counted."),
]
SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return SLUG.sub("-", str(text).lower()).strip("-") or "x"


def find_close(markup: str, start: int, tag: str) -> int:
    """The index just after the element that opens at `start`, or -1 when it does not close."""
    depth, pos = 0, start
    token = re.compile(r"<(/?)%s\b[^>]*?(/?)>" % tag)
    for m in token.finditer(markup, start):
        if m.group(1):
            depth -= 1
            if depth == 0:
                return m.end()
        elif not m.group(2):
            depth += 1
    return -1


def owner(row: str) -> Dict[str, str]:
    """What names a row among its kind: its wiki, kind, zone or kind of note, from its own attributes."""
    out = {}
    for name, attr in (("wiki", r'data-(?:mwikion|mw)="([^"]+)"'), ("kind", r'data-(?:mkind|mkl|kind)="([^"]+)"'),
                       ("zone", r'data-zone="([^"]+)"')):
        m = re.search(attr, row)
        if m:
            out[name] = slug(m.group(1))
    return out


def lookup(row: str) -> Optional[Tuple[str, str, str]]:
    """(key, name, text) of the row, or None when the table does not know it."""
    for needle, key, name, text in ROWS:
        if re.search(needle, row):
            try:
                return key % owner(row) if "%(" in key else key, name, text
            except KeyError:
                return None
    return None


def rows_of(section: str):
    """Every setting row of a section's markup, as (start, end, tag, row markup), in order. A row nested in another row of
    a class here is not taken twice."""
    found, until = [], 0
    for m in OPEN.finditer(section):
        if m.start() < until:
            continue
        classes = re.search(r'class="([^"]*)"', m.group(2))
        if not classes or not set(classes.group(1).split()) & set(ROW_CLASSES):
            continue
        end = find_close(section, m.start(), m.group(1))
        if end < 0:
            continue
        row = section[m.start():end]
        if not CONTROL.search(row) or "qhelp" in row:
            continue
        found.append((m.start(), end, m.group(1), row))
        until = end
    return found


def with_row_help(section: str, help_button: Callable[[str, str], str], help_text: Callable[[str, str], str]) -> str:
    """The section with a "?" in each setting row and its text under it. Each button stands at the end of its row."""
    for start, end, tag, row in reversed(rows_of(section)):
        known = lookup(row)
        if known is None:
            continue
        key, name, text = known
        close = row.rindex("</%s>" % tag)
        row = row[:close] + help_button(name, key) + row[close:]
        section = section[:start] + row + help_text(key, _html.escape(text)) + section[end:]
    return section


def unknown_rows(section: str) -> List[str]:
    """The rows of a section that have no "?" and that the table does not know: what a test names."""
    return [re.sub(r"\s+", " ", row)[:120] for _, _, _, row in rows_of(section) if lookup(row) is None]
