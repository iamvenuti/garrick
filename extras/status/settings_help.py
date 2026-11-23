#!/usr/bin/env python3
"""settings_help.py: one short help text per thing in Settings, and none where the label says it (#621, #681).

A section may have one "?" beside its heading, and a row may have one at its end. status.py builds each section's rows as
it always did; `with_row_help()` then finds each row of a section that the table below knows, gives it a "?" built by
status.py's own help_button(), and puts its text, made by help_text(), under it, hidden until the "?" is pressed. The
button stands at the end of its row, inside a label too: a button in a label does not toggle its box.

The rule every text keeps, and a test holds:

- A row has a "?" only when the user cannot guess something: a cost, something that leaves the computer or is kept,
  something that cannot be undone, or a word that needs a meaning. A row the table does not know has none.
- 30 words at most, two sentences at most.
- No file name, key, code, pattern, field name or name of an internal part.
- It does not repeat the label, the small line under the label, or the line under the section heading.
- Rows that repeat share one "?", on the first row of the group: a key with no name in it is given once in a section.
- A small line under a label has 10 words at most. The line under a section heading has 15 at most.
- One term per thing: notification, shortcut, this computer, working, dormant and archived, morning summary.

Saving is said once, at the foot of the dialog. Standard library only.
"""

from __future__ import annotations

import html as _html
import re
from typing import Callable, Dict, List, Optional, Tuple

# The class of each kind of row: an element with one of these, holding a control, is a setting row.
ROW_CLASSES = ("launcher-row", "zrow", "gkrow", "wallrow", "mkind", "mlists", "mpin", "setrelrow", "nsitem", "nsq", "rgrow")
CONTROL = re.compile(r"<(?:input|select|textarea)\b|<button\b[^>]*class=\"act[ \"]|class=\"(?:zbtn|rgchoice)\"|class=\"[^\"]*\bwchange\b|data-rolechange")
OPEN = re.compile(r'<(div|li|label|p)\b([^>]*)>')

# (a pattern found in the row's own markup, the key, the row's name, its text), the first that matches wins. The text is
# plain: `&` and quotes are escaped when it is put on the page.
ROWS: List[Tuple[str, str, str, str]] = [
    # Opening work
    (r'id="menu-show"', "menu-show", "Show the menu",
     "The menu icon turns red when a check on the Status tab fails."),
    (r'id="menu-style"', "menu-style", "Shows as",
     "A panel opens when the pointer rests at the top of that edge of the screen."),
    (r'id="menu-finder"', "menu-finder", "Right-click menu in Finder",
     "Adds Garrick to the right-click menu of a project folder. macOS asks you to switch it on, and the button opens that place."),
    # Ask
    (r'id="menu-ask"', "menu-ask", "Ask box",
     "On, Garrick keeps an assistant ready, and that uses some of your assistant's allowance. Off, the box opens your assistant instead."),
    (r'id="menu-dictkey"', "menu-dictkey", "Dictation shortcut",
     "Press the shortcut that starts your dictation app. If the app takes the keys, pause it first."),
    (r'id="ch-ask-tier"', "ch-tier", "Model size",
     "Start a message with deep: to get one answer on the large size at high effort, without changing this choice."),
    # choices-0800's one Answers choice (#683), Ask's and Telegram's sharing one "?": inert until it is in
    (r'data-answers="', "ch-answers", "Answers",
     "Start a message with deep: to get one Fuller answer without changing this choice."),
    (r'id="ch-ask-autonomy"', "ch-autonomy", "How far it may go",
     "Start with Read. Choose Act when you trust the answers."),
    # Notifications
    (r'data-nt="needs-you"', "nt-needs-you", "a session needs me",
     "A session waits for your permission, your answer or your approval. You get one notification for each wait."),
    (r'id="n-quiet"', "nt-quiet", "Quiet hours",
     "A session that needs you still gets through."),
    # Older pages
    (r'class="mkind"', "mem-kind", "Dormant after",
     "The age of a page counts from the date of its meeting, or the date its reading came out. Opening a page does not make it newer."),
    (r'data-mpin="', "mem-pin", "What keeps a page working",
     "Pages about a person, an organisation or a topic never become dormant. To pin a page, ask your assistant."),
    (r'id="m-wake"', "mem-wake", "Suggest bringing a page back",
     "Garrick suggests it and waits for your yes. An archived page comes back only when you pin it."),
    (r'id="m-reach"', "mem-reach", "Search",
     "Working and dormant pages also finds older ones. Working pages only is quicker and stays on recent work."),
    # About
    (r'id="rel-on"', "rel-on", "Check for updates",
     "Garrick looks at its public release page. It sends nothing about your work, and it never updates without you."),
    (r'id="usage-on"', "usage-on", "Count which cards I open",
     "Counts which cards you open, on this computer only. No name or text is kept, and nothing is sent."),
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
    """The section with a "?" in each setting row the table knows and its text under it, each key once: rows that repeat
    share the "?" of the first of them (#681). Each button stands at the end of its row."""
    first: Dict[str, int] = {}
    for start, end, tag, row in rows_of(section):
        known = lookup(row)
        if known is not None and known[0] not in first:
            first[known[0]] = start
    for start, end, tag, row in reversed(rows_of(section)):
        known = lookup(row)
        if known is None or first.get(known[0]) != start:
            continue
        key, name, text = known
        close = row.rindex("</%s>" % tag)
        row = row[:close] + help_button(name, key) + row[close:]
        section = section[:start] + row + help_text(key, _html.escape(text)) + section[end:]
    return section


def unknown_rows(section: str) -> List[str]:
    """The rows of a section that have no "?" and that the table does not know: what a test names."""
    return [re.sub(r"\s+", " ", row)[:120] for _, _, _, row in rows_of(section) if lookup(row) is None]
