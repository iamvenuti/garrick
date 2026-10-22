"""template/System/tools/operations.py: the durable record of a page action.

    python3 -m unittest discover -s tests

The identity key, the one mapping from outcome to sentence, and the journal:
what a worker writes, what a reader finds, and what stops a refusal from
reading as saved.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("garrick_operations_t", REPO / "template" / "System" / "tools" / "operations.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

pa_spec = importlib.util.spec_from_file_location("garrick_page_action_for_ops", REPO / "extras" / "status" / "page_action.py")
pa = importlib.util.module_from_spec(pa_spec)
pa_spec.loader.exec_module(pa)

# One request of each declared verb, as the status page sends it.
REQUESTS = {
    "park": {"verb": "park", "zone": "Work", "project": "Acme Review", "thread": "Pricing"},
    "wake": {"verb": "wake", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"},
    "todo-done": {"verb": "todo-done", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef"},
    "todo-undo": {"verb": "todo-undo", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef"},
    "todo-date": {"verb": "todo-date", "zone": "Work", "file": "Todo.md", "key": "0123456789abcdef", "date": "2026-10-12"},
    "todo-add": {"verb": "todo-add", "zone": "Work", "text": "Book the room", "target": "-", "date": "-"},
}
# What the code says when a check refuses or the worker falls over, and what a
# careless one might: every one of them must come out without a success.
REASONS = [
    "not committed, so nothing changed: the wall check refused: Acme Review/Acme Review.md names birch",
    "not committed: the wall check was still running after 5 minutes and was stopped, so the note was put back as it was. "
    "Make the change again and commit it by hand: that commit waits for the check and goes through",
    "not committed: x. The note was edited meanwhile, so it was left as it is, uncommitted; commit it by hand",
    "that line has changed since the page was built; it rebuilds now, try again",
    "another action in Work is still running; try again in a moment",
    "OSError: the disk went away",
    # said carelessly: the guard must replace these rather than pass them on
    "Saved elsewhere", "made, but not committed: the files are there", "it was parked already", "Ticked and added",
]
SUCCESS = re.compile(r"\b(%s)\b" % "|".join(ops.SUCCESS_VERBS), re.I)


def only_in_the_negative(sentence):
    """A stricter reading than the module's own: any success verb at all is a
    failure, except straight after "not " or "no "."""
    return all(re.search(r"\b(not|no)\s+$", sentence[:m.start()], re.I) for m in SUCCESS.finditer(sentence))


def status_py():
    sys.path.insert(0, str(REPO / "extras" / "status"))
    try:
        import status
        return status
    finally:
        sys.path.pop(0)


class TestDeclared(unittest.TestCase):
    def test_every_verb_it_declares_is_one_the_page_sends(self):
        self.assertEqual(sorted(REQUESTS), sorted(ops.OPS))
        for verb in ops.OPS:
            self.assertIn(verb, pa.VERBS, verb)
        for verb, spec in ops.OPS.items():
            self.assertTrue(set(spec.identity) <= set(spec.fields), verb)
            self.assertIn("zone", spec.fields, verb)
            self.assertNotIn("zone", spec.identity, verb)                 # the zone is always in the key, apart from them
            self.assertTrue(set(REQUESTS[verb]) - {"verb"} <= set(spec.fields), verb)   # nothing a real request carries is undeclared

    def test_the_table_declares_every_verb_and_nothing_else(self):
        # `checkpoint` is the one declared verb no page sends: confirming a
        # checkpoint is a wrap, and the page has no source for one.
        self.assertEqual(set(pa.VERBS) | set(pa.CMUX_VERBS) | {pa.JOURNAL_VERB} | {"checkpoint"},
                         set(ops.DECLARED))
        self.assertEqual(sorted(ops.RECORDED), sorted(ops.OPS))
        self.assertTrue(set(ops.RECORDED) <= set(ops.DECLARED))
        for verb, spec in ops.DECLARED.items():
            self.assertTrue(set(spec.identity) <= set(spec.fields), verb)
            self.assertIn(spec.scope, ops.SCOPES, verb)
            self.assertIn(spec.retry, ops.RETRIES, verb)
            self.assertIn(spec.precheck, ops.PRECHECKS, verb)
            self.assertIsInstance(spec.commits, bool, verb)
            self.assertEqual(len(set(spec.fields)), len(spec.fields), verb)
            self.assertFalse(set(spec.fields) & set(ops.ALWAYS), verb)    # verb and op belong to every verb
            if spec.commits:
                self.assertEqual("zone", spec.scope, verb)                # only a zone's repository is committed in

    def test_only_the_six_the_page_sends_under_the_lock_keep_a_record(self):
        """`OPS` is what page_action.py has read since 0.26.0. A newer copy of
        this file found by an older extra must not start recording verbs that
        extra knows nothing of, so the table grew and `OPS` did not."""
        self.assertEqual(("park", "wake", "todo-done", "todo-undo", "todo-date", "todo-add"), ops.RECORDED)
        for verb in ops.RECORDED:
            self.assertEqual(("zone", True), (ops.DECLARED[verb].scope, ops.DECLARED[verb].commits), verb)
            self.assertEqual("safe", ops.DECLARED[verb].retry, verb)

    def test_the_page_script_zones_cover_them(self):
        self.assertTrue(set(ops.OPS) <= set(status_py().ZONE_VERBS))

    def test_a_worker_and_a_reader_agree_on_the_words(self):
        self.assertEqual(("saved", "refused", "crashed", "unknown", "lost"), ops.OUTCOMES)
        self.assertEqual(("queued", "running", "completed", "failed"), ops.STATES)



class TestCheckpointDeclared(unittest.TestCase):
    """The checkpoint verb in the one table: declared, with its fields closed,
    and deliberately out of `RECORDED`."""

    def test_it_is_declared_with_the_fields_a_request_carries(self):
        spec = ops.DECLARED["checkpoint"]
        self.assertEqual(("zone", "project", "thread", "base", "prev", "items", "drop", "read"), spec.fields)
        self.assertEqual(("project", "thread"), spec.identity)
        self.assertEqual(("zone", False, "safe", "checkpoint"),
                         (spec.scope, spec.commits, spec.retry, spec.precheck))

    def test_its_fields_are_closed(self):
        req = {"verb": "checkpoint", "zone": "Work", "project": "Acme", "thread": "Pricing",
               "base": "9c1e4a7b20d3", "prev": None, "items": [], "drop": [], "read": True}
        self.assertIsNone(ops.validate("checkpoint", req))
        for field, value in (("where", "row 14"), ("file", "Acme/Threads/Pricing/Pricing.md"),
                             ("key", "abc"), ("confirm", "Pricing")):
            why = ops.validate("checkpoint", dict(req, **{field: value}))
            self.assertIsNotNone(why, field)
            self.assertIn(field, why, field)

    def test_it_keeps_no_journal_entry_and_so_never_meets_the_window(self):
        # A page action has no state of its own to compare a repeat against
        # before it runs; a checkpoint has the note, so IDEM_WINDOW cannot
        # reach it either way.
        self.assertNotIn("checkpoint", ops.RECORDED)
        self.assertNotIn("checkpoint", ops.OPS)
        self.assertIn("checkpoint", ops.DECLARED)

    def test_the_precheck_is_the_pair_the_writer_last_read(self):
        req = {"verb": "checkpoint", "zone": "Work", "project": "Acme", "thread": "Pricing",
               "base": "9c1e4a7b20d3", "prev": "5be0f1a2c3d4"}
        self.assertIsNone(ops.stale("checkpoint", req, ("9c1e4a7b20d3", "5be0f1a2c3d4")))
        for found in (("9c1e4a7b20d3", "0000deadbeef"), ("0000deadbeef", "5be0f1a2c3d4"), (None, None), None):
            why = ops.stale("checkpoint", req, found)
            self.assertEqual(ops.STALE_WHY[("checkpoint", None)], why, found)
            self.assertTrue(only_in_the_negative(why), why)
        first = {"verb": "checkpoint", "zone": "Work", "project": "Acme", "thread": "Pricing"}
        self.assertIsNone(ops.stale("checkpoint", first, (None, None)))      # nothing read, nothing there


# ---- what the page actually sends ----------------------------------------
# Closed validation means one field nobody enumerated stops a button working
# on every installed page the moment the extra updates. The page builds its
# requests three ways, and a test that read only the JavaScript would miss
# two of them, so the scanners below walk all three:
#
#   1. object literals in the page's own script (MANAGE_JS, PANEL_JS, TODO_JS,
#      WORK_JS): `{verb:'park',…}`, and the fields added after it as `q.x=…`;
#   2. `data-act` attributes assembled in Python with json.dumps, which is
#      where startup, shutdown and run come from;
#   3. `data-act` attributes built by the desk() helper for the cmux verbs,
#      and the one built in JS with JSON.stringify(q) in the dialogs — both
#      object literals, so scanner 1 finds them, and REGIONS below asserts
#      that the region they live in was really walked.
#
# A shape whose verb is a literal is checked against that verb. A shape whose
# verb is a variable is listed in SHAPES by the text of the value, with the
# verbs it can carry and any field added in a way no scanner can read. A new
# `verb:` or `json.dumps({"verb"` that SHAPES does not name fails the test.

KEY_RE = re.compile(r"\s*(?:'([A-Za-z_][\w-]*)'|\"([A-Za-z_][\w-]*)\"|([A-Za-z_][\w-]*))\s*:")
VERB_RE = re.compile(r"\{\s*(?:'verb'|\"verb\"|verb)\s*:")
VAR_RE = re.compile(r"(?:var\s+)?([A-Za-z_]\w*)\s*=\s*[^=;{]*$")


def _literal(text, start):
    """The object literal that begins at text[start] == '{', to its matching
    brace, with what is inside quotes skipped."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    raise AssertionError("an object literal with no end at %d" % start)


def _pairs(literal):
    """[(name, the value's text)] for the top level of an object literal."""
    out, i, end = [], 1, len(literal) - 1
    while i < end:
        while i < end and literal[i] in " \t\r\n,":
            i += 1
        m = KEY_RE.match(literal, i)
        if not m:
            break
        name, i = m.group(1) or m.group(2) or m.group(3), m.end()
        start, depth, quote = i, 0, None
        while i < end:
            c = literal[i]
            if quote:
                if c == "\\":
                    i += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c in "{[(":
                depth += 1
            elif c in "}])":
                depth -= 1
            elif c == "," and depth == 0:
                break
            i += 1
        out.append((name, literal[start:i].strip()))
        i += 1
    return out


SCRIPT_RE = re.compile(r'(?m)^([A-Z][A-Z_]*) = r"""\n')


def scripts(text):
    """The page's scripts, by the name status.py keeps each in: {name: (the
    text, where it starts in the file)}. Everything else is the Python half."""
    out, ends = {}, []
    for m in SCRIPT_RE.finditer(text):
        end = text.index('\n"""', m.end())
        out[m.group(1)] = (text[m.end():end], m.end())
        ends.append((m.start(), end))
    rest = text
    for start, end in reversed(ends):               # the Python half, the scripts cut out
        rest = rest[:start] + rest[end:]
    return out, rest


FUNC_RE = re.compile(r"(?:function\s+([A-Za-z_]\w*)\s*\(|([A-Za-z_][\w.]*)\s*=\s*function\s*\()")


def shapes(text, line0=1):
    """Every request shape built in `text`: (the function it is built in and
    the verb value's text, the field names, the line it is on). A shape's
    fields are what the literal holds plus what the next two lines add to the
    variable it was assigned to."""
    funcs = [(m.start(), m.group(1) or m.group(2)) for m in FUNC_RE.finditer(text)]
    found = []
    for m in VERB_RE.finditer(text):
        literal = _literal(text, m.start())
        pairs = dict(_pairs(literal))
        fields = set(pairs)
        line = line0 + text.count("\n", 0, m.start())
        head = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        var = VAR_RE.search(head)
        if var:            # `if(mg[2])q.thread=mg[2]`, `if(zChanged)q.zones=zreq()`
            after = text[m.start() + len(literal):]
            after = "\n".join(after.split("\n")[:3])
            fields |= set(re.findall(r"\b%s\.([A-Za-z_]\w*)\s*=[^=]" % re.escape(var.group(1)), after))
        where = next((name for at, name in reversed(funcs) if at < m.start()), "(top level)")
        found.append(("%s: %s" % (where, pairs["verb"]), frozenset(fields), line))
    return found


# The verbs each shape can carry, and the fields it adds where no scanner can
# read them. Keyed by the text of the `verb` value, exactly as the file has it.
ZONED = ("todo-done", "todo-undo", "todo-date", "todo-add", "park", "wake", "new-project", "new-thread",
         "rename", "delete", "undo", "interrupt", "answer", "later", "continue", "fix", "suggestion", "start",
         "stop-using", "bring-back", "files")
SHAPES = {
    # --- 1. object literals in the page's own script ----------------------
    # MANAGE_JS: the dialogs, each sent from the Make it / Rename / Delete button
    "onclick: 'new-thread'": {"new-thread": ()},
    "onclick: 'new-project'": {"new-project": ()},
    "onclick: 'rename'": {"rename": ()},
    "onclick: 'park'": {"park": ()},                     # del(): Park instead
    "onclick: 'delete'": {"delete": ()},
    "onclick: 'undo'": {"undo": ()},                     # offer(): the undo bar
    "poll: 'operations'": {"operations": ()},            # WORK_JS: the one verb that reads
    # TODO_JS send(verb,r,more,said); `more` is {date:v} from the date menu,
    # merged by `for(var k in more)`, which no scanner of the literal sees
    "send: verb": {"todo-done": (), "todo-undo": (), "todo-date": ("date",)},
    "held: verb": {"todo-done": (), "todo-date": ()},    # TODO_JS: the busy check, not a request
    # TODO_JS: a box ticked on the Todo tab or in a thread's todo list on the Threads card (#179),
    # handed to WORK_JS's queue
    "onTick: verb": {"todo-done": (), "todo-undo": ()},
    "request: 'settings'": {"settings": ()},             # PANEL_JS GarrickPrefs.request()
    "window.TaddSend: 'todo-add'": {"todo-add": ()},     # JS: the Todo list's + button
    "sdReq: 'settings'": {"settings": ()},               # JS: what Settings closes with, zones and notifications alone
    # NOTIFY_JS: Send a test and Telegram's Set up…, the settings with them (#110); `more` is merged by
    # `for(var k in more)`, which no scanner of the literal sees
    "nact: 'settings'": {"settings": ("test", "token", "find-chat")},
    # --- 3. data-act built by desk() and by JSON.stringify(q) -------------
    "deskReq: v": {"open": (), "close": ()},             # PANEL_JS, through desk(o,v)
    "park: v": {"park": (), "wake": ()},                 # PANEL_JS park(o): by name, or by file
    "cont: 'continue'": {"continue": ()},                # PANEL_JS cont(o): Open in Claude on a thread (#180)
    # the page's own cache entries, which are never sent back: their verbs
    # are the zoned ones, and `op` is what GarrickAct adds to what it sends
    "reconcile: r.verb": {verb: () for verb in ZONED},           # WORK_JS
    "window.GarrickActed: q.verb": {verb: () for verb in ZONED},  # WORK_JS
    # WORK_JS's queue of ticks (#107): an entry it keeps, and the batch it sends
    "window.GarrickTick: q.verb": {"todo-done": (), "todo-undo": ()},
    "flush: one.verb": {"todo-done": (), "todo-undo": ()},
    # SIMPLE_JS (#175): Ask something, and Settings › Home
    "askReq: 'ask-desktop'": {"ask-desktop": ()},
    # Your own work (#182): a suggestion renamed, and a next step in the user's own words; a suggestion's
    # Yes, Not and Rename carry the part of the workspace chosen above them, merged by Object.assign
    "renameReq: 'suggestion'": {"suggestion": ("zone", "party", "owner")},
    "ownReq: 'answer'": {"answer": ()},
    "homeReq: 'settings'": {"settings": ()},
    # WHERE_JS (#189): how far a copy or a move has got, which only reads; Stop; and a version opened or saved,
    # `to` added by the Mac app's Save panel
    "poll: 'files-progress'": {"files-progress": ()},
    "vreq: 'files-stop'": {"files-stop": ()},
    "vreq: 'work-file'": {"work-file": ("to",)},
}
# --- 2. assembled in Python with json.dumps, straight into data-act -------
PY_SHAPES = {'"startup"': ("startup",), '"shutdown"': ("shutdown",), '"run"': ("run",),
             # the simple home (#175): Continue, a Needs you answer and Not now, the example's two links
             '"continue"': ("continue",), '"answer"': ("answer",), '"later"': ("later",), '"example"': ("example",),
             # a `check` chip's Fix on the Threads card (#179)
             '"fix"': ("fix",),
             # your own work (#182): a suggestion's Yes and Not, Start, Stop using this and Bring it back
             '"suggestion"': ("suggestion",), '"start"': ("start",), '"stop-using"': ("stop-using",),
             '"bring-back"': ("bring-back",),
             # where a work's files live (#189): Keep a copy, a move and the rest; a moved file opened, Finder
             '"files"': ("files",), '"work-file"': ("work-file",)}
# Which script each shape is built in, so that a script gaining a shape, or
# losing the one it had, is a failure rather than a quiet gap.
SCRIPTS = {"MANAGE_JS": {"onclick: 'new-thread'", "onclick: 'new-project'", "onclick: 'rename'",
                         "onclick: 'park'", "onclick: 'delete'", "onclick: 'undo'"},
           "WORK_JS": {"poll: 'operations'", "reconcile: r.verb", "window.GarrickActed: q.verb", "window.GarrickTick: q.verb",
                       "flush: one.verb"},
           "TODO_JS": {"send: verb", "held: verb", "onTick: verb"},
           "PANEL_JS": {"request: 'settings'", "deskReq: v", "park: v", "cont: 'continue'"},
           "JS": {"window.TaddSend: 'todo-add'", "sdReq: 'settings'"},
           "NOTIFY_JS": {"nact: 'settings'"},
           "SIMPLE_JS": {"askReq: 'ask-desktop'", "homeReq: 'settings'", "renameReq: 'suggestion'", "ownReq: 'answer'"},
           "WHERE_JS": {"poll: 'files-progress'", "vreq: 'files-stop'", "vreq: 'work-file'"}}


class TestWhatThePageSends(unittest.TestCase):
    """The obligation that comes with refusing an unknown field."""

    def setUp(self):
        self.text = (REPO / "extras" / "status" / "status.py").read_text(encoding="utf-8")
        self.scripts, self.python = scripts(self.text)
        self.found = {}                         # script name -> the shapes in it
        for name, (body, at) in self.scripts.items():
            self.found[name] = shapes(body, line0=self.text.count("\n", 0, at) + 1)

    def declared(self, verb):
        return set(ops.DECLARED[verb].fields) | set(ops.ALWAYS)

    def check(self, verbs, fields, where):
        """`verbs` is {verb: the fields it adds where no scanner can read them}."""
        for verb, added in (verbs.items() if isinstance(verbs, dict) else ((v, ()) for v in verbs)):
            undeclared = (set(fields) | set(added)) - self.declared(verb)
            self.assertEqual(set(), undeclared, "%s sends %s to %s" % (where, sorted(undeclared), verb))

    def test_every_field_the_page_script_sends_is_declared(self):
        seen = 0
        for name, found in self.found.items():
            for value, fields, line in found:
                self.check(SHAPES[value], fields, "status.py:%d (%s)" % (line, name))
                seen += 1
        self.assertGreaterEqual(seen, len(SHAPES))

    def test_every_shape_assembled_in_python_is_declared_too(self):
        found = {}
        for m in re.finditer(r"json\.dumps\(\{\s*\"verb\"\s*:", self.python):
            pairs = dict(_pairs(_literal(self.python, m.start() + len("json.dumps("))))
            found[pairs["verb"]] = set(pairs)
        self.assertEqual(set(PY_SHAPES), set(found), 'a json.dumps({"verb"…}) shape this test does not name')
        for value, fields in found.items():
            self.check(PY_SHAPES[value], fields, 'json.dumps({"verb": %s…})' % value)

    def test_nothing_else_in_the_python_half_builds_a_request(self):
        """Source 2 is json.dumps and nothing else. A request assembled any
        other way in Python would not be walked above."""
        for line in self.python.splitlines():
            if '{"verb"' in line and not line.lstrip().startswith("#"):
                self.assertIn("json.dumps({\"verb\"", line.replace(" ", "").replace('{"verb":', '{"verb"'), line)

    def test_a_shape_the_test_does_not_name_is_a_failure(self):
        found = {value for found in self.found.values() for value, _, _ in found}
        self.assertEqual(set(SHAPES), found, "a `verb:` in a page script that SHAPES does not account for")

    def test_each_script_holds_the_shapes_it_is_said_to(self):
        """Which is what fails when a scanner walks past a region: a shape
        that moved, or a script that gained one, shows up here."""
        for name, found in self.found.items():
            self.assertEqual(SCRIPTS.get(name, set()), {value for value, _, _ in found}, name)
        self.assertEqual(set(SCRIPTS), {n for n, f in self.found.items() if f})

    def test_the_op_every_sent_request_carries_is_declared_for_all_of_them(self):
        """WORK_JS's GarrickAct adds `op` to each request it sends, through
        Object.assign, which no scanner of the literals sees."""
        self.assertIn("op", ops.ALWAYS)
        self.assertRegex(self.text, r"Object\.assign\(\{\},q,\{op:q\.op\|\|mint\(\)\}\)")
        # `retry_of`, which a retry button would add (the design's §2), is not
        # declared yet: whoever adds the button adds it to ALWAYS here first.
        self.assertNotIn("retry_of", ops.ALWAYS)
        self.assertNotIn("retry_of", self.text)

    def test_what_is_built_outside_status_py_is_declared(self):
        """The hosts and the ask box build their own, where no scan of
        status.py reaches: an open by folder from the app and the plugin, and
        what ask.py proposes. The threads skill's JSON is checked by hand
        against its SKILL.md below."""
        host = {"verb", "folder", "prompt"}                    # Garrick.swift act(), obsidian/main.js
        self.assertEqual(set(), host - self.declared("open"))
        for name, text in (("app/Garrick.swift", (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text()),
                           ("obsidian/main.js", (REPO / "extras" / "status" / "obsidian" / "main.js").read_text())):
            self.assertIn("verb", text, name)
        ask = (REPO / "extras" / "status" / "ask.py").read_text(encoding="utf-8")
        for m in re.finditer(r"\{\s*\"verb\"\s*:", ask):
            pairs = dict(_pairs(_literal(ask, m.start())))
            verbs = ("park", "wake") if pairs["verb"] == "verb" else (pairs["verb"].strip('"'),)
            for verb in verbs:
                self.assertEqual(set(), set(pairs) - self.declared(verb), (verb, sorted(pairs)))

    def test_the_threads_skill_sends_what_the_table_declares(self):
        skill = (REPO / "template" / "System" / "skills" / "threads" / "SKILL.md").read_text(encoding="utf-8")
        for m in re.finditer(r"\{\s*\"verb\"\s*:", skill):
            line = skill[m.start():skill.index("\n", m.start())]
            verb = re.search(r"\"verb\"\s*:\s*\"([\w-]+)\"", line).group(1)
            # the keys as the skill writes them, with or without a value
            fields = set(re.findall(r"\"([a-z_]+)\"", line)) - {"verb", verb}
            self.assertEqual(set(), fields - self.declared(verb), (verb, line))


class TestValidation(unittest.TestCase):
    """Closed from the first slice: a field the verb does not declare is
    refused by name, rather than logged and allowed."""

    def test_a_real_request_of_every_verb_passes(self):
        for verb, req in REQUESTS.items():
            self.assertIsNone(ops.validate(verb, req), verb)
            self.assertIsNone(ops.validate(verb, dict(req, op="a19f3c80")), verb)

    def test_an_undeclared_field_is_refused_by_name(self):
        why = ops.validate("park", dict(REQUESTS["park"], scope="everything"))
        self.assertEqual("park takes no scope field", why)
        self.assertEqual(["scope"], ops.undeclared("park", dict(REQUESTS["park"], scope="x")))

    def test_several_are_all_named_in_one_sentence(self):
        why = ops.validate("todo-add", dict(REQUESTS["todo-add"], password="hunter2", host="app"))
        self.assertEqual("todo-add takes no host field and no password field", why)

    def test_the_refusal_names_a_field_even_when_the_field_is_called_saved(self):
        """The sentence must name it and still not read as a success, however
        the field is spelled: the negation is repeated before each name."""
        for name in ops.SUCCESS_VERBS:
            why = ops.validate("park", dict(REQUESTS["park"], **{name: 1}))
            said = ops.say("refused", "park", REQUESTS["park"], why=why)
            self.assertIn(name, said, name)
            self.assertFalse(ops.affirms(said), said)
            self.assertTrue(only_in_the_negative(said), said)

    def test_a_field_name_is_cut_short_and_put_on_one_line(self):
        why = ops.validate("park", dict(REQUESTS["park"], **{"x" * 200: 1, "two\nlines": 2}))
        self.assertNotIn("\n", why)
        self.assertLess(len(why), 140)

    def test_a_verb_the_table_does_not_declare_is_not_judged_here(self):
        self.assertIsNone(ops.validate("rm", {"verb": "rm", "anything": 1}))
        self.assertIsNone(ops.validate("park", ["not", "a", "dict"]))


class TestPrecheck(unittest.TestCase):
    """What must still be true for a request to run. The fingerprint is read
    by the caller, from the file: nothing here computes one."""

    def test_a_todo_line_that_has_moved_is_refused(self):
        for verb in ("todo-done", "todo-undo", "todo-date"):
            req = REQUESTS[verb]
            self.assertIsNone(ops.stale(verb, req, req["key"]), verb)              # a line still has it
            why = ops.stale(verb, req, None)                                       # none does
            self.assertEqual("that line has changed since the page was built; it rebuilds now, try again", why)
            self.assertTrue(only_in_the_negative(ops.say("refused", verb, req, why=why)))

    def test_a_second_park_of_a_parked_thread_says_so(self):
        req = REQUESTS["park"]
        self.assertEqual("Pricing was set aside already, so nothing was changed", ops.stale("park", req, "parked"))
        self.assertEqual("Pricing is active already, so nothing was changed",
                         ops.stale("wake", dict(req, verb="wake"), "ACTIVE "))     # as the frontmatter spells it
        for status in ("active", "done", "", None, "parked-ish"):
            self.assertIsNone(ops.stale("park", req, status), status)
        for status in ("parked", "done", "", None):
            self.assertIsNone(ops.stale("wake", req, status), status)

    def test_neither_refusal_reads_as_a_success(self):
        for verb, found in (("park", "parked"), ("wake", "active")):
            said = ops.say("refused", verb, REQUESTS[verb], why=ops.stale(verb, REQUESTS[verb], found))
            self.assertTrue(only_in_the_negative(said), said)
            self.assertFalse(ops.affirms(said), said)
            self.assertIn("nothing was changed", said)

    def test_a_verb_whose_handler_checks_for_itself_has_none(self):
        self.assertIsNone(ops.DECLARED["todo-add"].precheck)     # a line already there is refused by the handler
        self.assertIsNone(ops.stale("todo-add", REQUESTS["todo-add"], None))
        self.assertIsNone(ops.stale("new-project", {"verb": "new-project"}, None))
        self.assertIsNone(ops.stale("rm", {}, None))


class TestIdentityKey(unittest.TestCase):
    def test_the_same_request_has_the_same_key(self):
        for verb, req in REQUESTS.items():
            key = ops.identity_key(verb, req)
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            self.assertEqual(key, ops.identity_key(verb, dict(reversed(list(req.items())))), verb)    # order
            self.assertEqual(key, ops.identity_key(verb, dict(req, op="a19f3c80", retry_of="x", host="app", junk=1)), verb)

    def test_a_missing_field_and_an_empty_one_say_the_same(self):
        bare = {"verb": "todo-add", "zone": "Work", "text": "Book the room"}
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", REQUESTS["todo-add"]))
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", dict(bare, target=None, date="")))
        self.assertEqual(ops.identity_key("todo-add", bare), ops.identity_key("todo-add", dict(bare, text="  Book the room ")))
        park = {"verb": "park", "zone": "Work", "project": "Acme Review"}
        self.assertEqual(ops.identity_key("park", park), ops.identity_key("park", dict(park, thread=None, file="")))

    def test_a_meaningful_change_is_a_different_key(self):
        for verb, req in REQUESTS.items():
            base = ops.identity_key(verb, req)
            self.assertNotEqual(base, ops.identity_key(verb, dict(req, zone="Personal")), verb)
            for field in ops.OPS[verb].identity:
                changed = dict(req, **{field: "something else"})
                self.assertNotEqual(base, ops.identity_key(verb, changed), (verb, field))
        self.assertNotEqual(ops.identity_key("park", REQUESTS["park"]), ops.identity_key("wake", REQUESTS["park"]))

    def test_a_client_cannot_choose_it(self):
        req = dict(REQUESTS["park"], key="deadbeefdeadbeef", identity="x")
        self.assertEqual(ops.identity_key("park", REQUESTS["park"]), ops.identity_key("park", req))

    def test_the_op_is_checked_for_its_shape_only(self):
        for good in ("a19f3c80", "0" * 32, ops.mint_op()):
            self.assertTrue(ops.valid_op(good), good)
        for bad in ("", "A19F3C80", "a19f3c8", "g" * 8, "0" * 33, None, 12345678, "a19f3c80\n", "../a19f3c80"):
            self.assertFalse(ops.valid_op(bad), bad)


class TestBatch(unittest.TestCase):
    """#107: a tick or untick naming several lines by `keys`, one request."""

    A, B, C = "0123456789abcdef", "fedcba9876543210", "00112233445566ff"

    def batch(self, *keys, verb="todo-done"):
        return dict(REQUESTS[verb], keys=list(keys), key=None)

    def test_the_lines_of_a_batch_are_one_set_and_a_batch_of_one_is_the_line(self):
        for verb in ("todo-done", "todo-undo"):
            ab = ops.identity_key(verb, self.batch(self.A, self.B, verb=verb))
            self.assertEqual(ab, ops.identity_key(verb, self.batch(self.B, self.A, verb=verb)), verb)     # the order ticked
            self.assertEqual(ab, ops.identity_key(verb, self.batch(self.A, self.B, self.A, verb=verb)), verb)
            self.assertNotEqual(ab, ops.identity_key(verb, self.batch(self.A, self.B, self.C, verb=verb)), verb)
            self.assertEqual(ops.identity_key(verb, REQUESTS[verb]), ops.identity_key(verb, self.batch(self.A, verb=verb)), verb)
        self.assertNotEqual(ops.identity_key("todo-done", self.batch(self.A, self.B)),
                            ops.identity_key("todo-undo", self.batch(self.A, self.B, verb="todo-undo")))

    def test_only_a_tick_or_an_untick_takes_keys(self):
        self.assertIsNone(ops.validate("todo-done", self.batch(self.A)))
        self.assertIsNone(ops.validate("todo-undo", self.batch(self.A)))
        for verb in ("todo-date", "todo-add", "park"):
            self.assertEqual("%s takes no keys field" % verb, ops.validate(verb, dict(REQUESTS[verb], keys=[self.A])), verb)

    def test_a_batch_is_labelled_by_its_count(self):
        self.assertEqual("Ticking 3 lines…", ops.label("todo-done", self.batch(self.A, self.B, self.C)))
        self.assertEqual("Already reopening those 2 lines…", ops.label("todo-undo", self.batch(self.A, self.B), already=True))
        self.assertEqual("Ticking that line…", ops.label("todo-done", self.batch(self.A)))
        self.assertIn("those Todo lines", ops.say("unknown", "todo-done", self.batch(self.A, self.B)))

    def test_a_wall_refusal_is_the_rules_sentence_and_nothing_else(self):
        """#116's words, as #107 has a refused batch end on them: say() adds no
        refusal wording of its own, and the sentence affirms nothing."""
        wall = ops.WALL_REFUSAL
        for verb in ("todo-done", "todo-undo"):
            self.assertEqual(wall, ops.say("refused", verb, self.batch(self.A, self.B, verb=verb), why=wall))
            self.assertEqual(wall, ops.say("refused", verb, REQUESTS[verb], why=" %s " % wall))
        self.assertFalse(ops.affirms(wall))
        self.assertTrue(only_in_the_negative(wall))
        self.assertEqual("Not done. Commit refused.", ops.say("refused", "todo-done", REQUESTS["todo-done"], why="commit refused"))


class TestWording(unittest.TestCase):
    """What stops a refusal reading as saved: one mapping, and a test that asserts the negative."""

    def test_only_saved_may_say_what_the_handler_said(self):
        for verb, req in REQUESTS.items():
            self.assertEqual("Acme Review is parked", ops.say("saved", verb, req, said="Acme Review is parked"))
            for outcome in ops.OUTCOMES[1:]:
                self.assertNotIn("Acme Review is parked", ops.say(outcome, verb, req, why="x", said="Acme Review is parked"))

    def test_no_failure_for_any_verb_reads_as_a_success(self):
        for verb, req in REQUESTS.items():
            for outcome in ops.OUTCOMES:
                if outcome == "saved":
                    continue
                for why in REASONS:
                    sentence = ops.say(outcome, verb, req, why=why, said="Everything was saved, parked, ticked and added")
                    self.assertTrue(only_in_the_negative(sentence), (verb, outcome, why, sentence))
                    self.assertFalse(ops.affirms(sentence), (verb, outcome, why, sentence))

    def test_the_templates_hold_no_success_verb_at_all(self):
        for outcome, template in ops.SAYINGS.items():
            self.assertIsNone(SUCCESS.search(template), outcome)
            self.assertIsNone(SUCCESS.search(ops.FALLBACK_WHY.get(outcome, "")), outcome)
        for verb, req in REQUESTS.items():
            for already in (False, True):                       # a join says a request is under way, never that it is done
                self.assertIsNone(SUCCESS.search(ops.label(verb, req, already=already)), verb)
            for outcome in ("unknown", "lost"):
                self.assertIsNone(SUCCESS.search(ops.say(outcome, verb, req)), (verb, outcome))

    def test_an_unknown_one_says_what_to_check_and_that_trying_again_is_safe(self):
        said = ops.say("unknown", "park", REQUESTS["park"])
        self.assertIn("We do not know whether the change to Pricing went through", said)
        self.assertIn("git log -1 in Work", said)
        self.assertIn("Trying again is safe", said)

    def test_the_guard_reads_negatives_and_affirmatives(self):
        for fine in ("Not committed, so nothing changed", "left as it is, uncommitted", "was not saved", "Make the change again",
                     "nothing was parked", "never ticked"):
            self.assertFalse(ops.affirms(fine), fine)
        for bad in ("Saved", "made, but not committed", "It was added to Inbox", "committed", "Parked."):
            self.assertTrue(ops.affirms(bad), bad)

    def test_a_terminal_record_without_a_valid_outcome_is_a_programming_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = ops.Journal(tmp)
            base = {"op": "a19f3c80", "verb": "park", "zone": "Work", "at": 1.0}
            for rec in (dict(base, state="failed"), dict(base, state="failed", outcome="nope"), dict(base, state="completed"),
                        dict(base, state="completed", outcome="refused"), dict(base, state="failed", outcome="saved"),
                        dict(base, state="finished", outcome="saved")):
                with self.assertRaises(ValueError, msg=rec):
                    j.append(rec)
            self.assertEqual([], j.records())
        with self.assertRaises(ValueError):
            ops.say("fine", "park", REQUESTS["park"])


class JournalCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "jobs"
        self.j = ops.Journal(self.folder)
        self.runs = []

    def tearDown(self):
        for run in self.runs:
            run.close(REQUESTS["park"])
        self._tmp.cleanup()

    def start(self, verb="park", now=None, **extra):
        run, reply = ops.start(self.folder, dict(REQUESTS[verb], **extra), now=now)
        if run is not None:
            self.runs.append(run)
        return run, reply


class TestJournal(JournalCase):
    def test_a_record_runs_from_queued_to_a_terminal_state(self):
        run, reply = self.start(op="a19f3c80")
        self.assertIsNone(reply)
        run.running()
        run.phase("checking")
        said = run.finish("saved", REQUESTS["park"], said="Pricing is parked")
        run.close(REQUESTS["park"])
        self.assertEqual({"ok": True, "say": "Pricing is parked", "op": "a19f3c80", "state": "completed", "outcome": "saved"}, said)
        records = self.j.records()
        self.assertEqual([("queued", ""), ("running", ""), ("running", "checking"), ("completed", "")],
                         [(r["state"], r["phase"]) for r in records])
        self.assertEqual({"a19f3c80"}, {r["op"] for r in records})
        self.assertEqual("saved", records[-1]["outcome"])
        self.assertEqual({"zone": "Work", "project": "Acme Review", "thread": "Pricing"}, records[0]["request"])
        self.assertEqual(ops.identity_key("park", REQUESTS["park"]), records[0]["key"])
        self.assertEqual("Parking Pricing…", records[0]["label"])
        self.assertFalse(self.j.run_path("a19f3c80").exists())                 # the lock file goes with the run

    def test_the_request_holds_only_what_the_verb_declares_and_a_line_cut_short(self):
        run, _ = self.start("todo-add", text="x" * 200, password="hunter2", op="a19f3c80")
        text = self.j.path.read_text()
        self.assertNotIn("hunter2", text)
        self.assertLess(len(json.loads(text.splitlines()[0])["request"]["text"]), 70)

    def test_a_refusal_is_failed_and_refused_and_never_completed(self):
        run, _ = self.start(op="a19f3c80")
        said = run.finish("refused", REQUESTS["park"], why="not committed, so nothing changed: the wall check refused")
        self.assertEqual((False, "failed", "refused"), (said["ok"], said["state"], said["outcome"]))
        self.assertTrue(only_in_the_negative(said["say"]), said["say"])
        self.assertEqual("failed", self.j.records()[-1]["state"])

    def test_closing_without_a_terminal_record_leaves_a_crashed_one(self):
        run, _ = self.start(op="a19f3c80")
        run.close(REQUESTS["park"])
        last = self.j.records()[-1]
        self.assertEqual(("failed", "crashed"), (last["state"], last["outcome"]))
        self.assertIsNone(SUCCESS.search(last["say"]))

    def test_the_last_line_for_an_op_wins_and_a_torn_line_is_skipped(self):
        run, _ = self.start(op="a19f3c80")
        with open(self.j.path, "a") as f:
            f.write("{not json\n\n[1]\n")
        run.running()
        self.assertEqual("running", self.j.latest()["a19f3c80"]["state"])
        self.assertEqual(1, len(self.j.latest()))

    def test_a_bad_op_is_refused_for_its_shape(self):
        with self.assertRaises(ops.BadOp):
            ops.start(self.folder, dict(REQUESTS["park"], op="../../etc"))
        self.assertFalse(self.j.path.exists() and self.j.path.read_text())

    def test_an_op_left_out_is_minted(self):
        run, _ = self.start()
        self.assertTrue(ops.valid_op(run.op))

    def test_the_folder_nobody_can_write_gives_nothing_to_do(self):
        (self.folder).mkdir(parents=True)
        self.j.path.mkdir()                                                    # a folder where the journal should be
        self.assertEqual((None, None), ops.start(self.folder, REQUESTS["park"]))
        reply = ops.read(self.folder)
        self.assertEqual((True, False, []), (reply["ok"], reply["durable"], reply["ops"]))


class TestJoin(JournalCase):
    def test_an_identical_request_under_way_joins_and_executes_nothing(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.running()
        run, reply = self.start(op="b29f3c80", now=1030.0)
        self.assertIsNone(run)
        self.assertEqual({"ok": True, "say": "Already parking Pricing…", "op": "a19f3c80", "state": "running"}, reply)
        self.assertNotIn("outcome", reply)                                    # a join is ok, and is not a save
        self.assertIsNone(SUCCESS.search(reply["say"]))
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.j.records()})   # the second left no record of its own
        self.assertFalse(self.j.run_path("b29f3c80").exists())

    def test_the_same_op_twice_is_one_run(self):
        self.start(op="a19f3c80")
        run, reply = self.start(op="a19f3c80")
        self.assertIsNone(run)
        self.assertEqual(("a19f3c80", "running"), (reply["op"], reply["state"]))

    def test_a_different_request_does_not_join(self):
        self.start(op="a19f3c80", now=1000.0)
        run, reply = self.start(op="b29f3c80", now=1001.0, thread="Other")
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_outside_the_window_it_is_asked_about_and_does_not_run(self):
        """#137: still running, but long enough that this is not a double click."""
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.running()
        run, reply = self.start(op="b29f3c80", now=1000.0 + ops.IDEM_WINDOW + 60)
        self.assertIsNone(run)
        self.assertEqual((False, "asked", "a19f3c80", "a19f3c80"), (reply["ok"], reply["state"], reply["op"], reply["again"]))
        self.assertTrue(reply["say"].startswith("The same request is still running, started 3 minutes ago, at "), reply["say"])
        self.assertIn(": Parking Pricing. It has not been sent again. Do you want it done a second time once that one ends?",
                      reply["say"])
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.j.records()})
        run, reply = self.start(op="c39f3c80", now=1000.0 + ops.IDEM_WINDOW + 61, confirm="a19f3c80")
        self.assertIsNotNone(run)                                               # confirmed: it queues behind the first
        self.assertIsNone(reply)

    def test_a_dead_worker_is_not_joined(self):
        self.start(op="a19f3c80", now=1000.0)[0]
        os.close(self.runs[0].fd)                                              # the worker is gone, its lock with it
        self.runs[0].fd = os.open(os.devnull, os.O_RDONLY)
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)
        self.assertEqual("unknown", self.j.latest()["a19f3c80"]["outcome"])

    def test_a_save_just_made_is_returned_and_nothing_runs(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("saved", REQUESTS["park"], said="Acme Review, Pricing is parked")
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNone(run)
        self.assertEqual({"ok": True, "say": "Acme Review, Pricing is parked", "op": "a19f3c80", "state": "completed",
                          "outcome": "saved"}, reply)

    def test_a_refusal_is_not_cached(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("refused", REQUESTS["park"], why="a wall")
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_a_crash_is_not_cached_either(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.close(REQUESTS["park"])
        run, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertIsNotNone(run)

    def test_park_then_wake_then_park_is_three_edits(self):
        """The same park, asked again after a wake in between, is a new request."""
        for i, verb in enumerate(("park", "wake", "park")):
            req = dict(REQUESTS["park"], verb=verb)
            run, reply = ops.start(self.folder, dict(req, op="a19f3c8%d" % i), now=1000.0 + 10 * i)
            self.assertIsNone(reply, verb)
            run.finish("saved", req, said="done")
            run.close(req)

    def test_a_save_in_another_zone_does_not_hide_the_replay(self):
        first, _ = self.start(op="a19f3c80", now=1000.0)
        first.finish("saved", REQUESTS["park"], said="Acme Review, Pricing is parked")
        first.close(REQUESTS["park"])
        other = dict(REQUESTS["todo-add"], zone="Personal", op="c39f3c80")
        run, _ = ops.start(self.folder, other, now=1005.0)
        run.finish("saved", other, said="Added")
        run.close(other)
        _, reply = self.start(op="b29f3c80", now=1010.0)
        self.assertEqual("a19f3c80", reply["op"])


class TestRepeatedLater(JournalCase):
    """#137: past the double click's window, a request the record holds is not
    run again unasked. It is told what was done and when, and asked."""

    def saved(self, op="a19f3c80", said="Acme Review, Pricing is parked"):
        first, reply = self.start(op=op)
        self.assertIsNone(reply)
        first.finish("saved", REQUESTS["park"], said=said)
        first.close(REQUESTS["park"])
        self.runs.remove(first)
        return self.j.latest()[op]["done"]

    def test_a_double_click_inside_the_window_is_answered_and_runs_nothing(self):
        done = self.saved()
        run, reply = self.start(op="b29f3c80", now=done + ops.IDEM_WINDOW - 1)
        self.assertIsNone(run)
        self.assertEqual({"ok": True, "say": "Acme Review, Pricing is parked", "op": "a19f3c80", "state": "completed",
                          "outcome": "saved"}, reply)

    def test_a_retry_past_the_window_is_asked_about_and_runs_nothing(self):
        done = self.saved()
        run, reply = self.start(op="b29f3c80", now=done + 300)
        self.assertIsNone(run)
        at = time.strftime("%H:%M", time.localtime(done))
        self.assertEqual({"ok": False, "op": "a19f3c80", "state": "asked", "again": "a19f3c80",
                          "say": "The same request was done 5 minutes ago, at %s: Acme Review, Pricing is parked. It has "
                                 "not been done again. Do you want it done a second time?" % at}, reply)
        self.assertEqual({"a19f3c80"}, {r["op"] for r in self.j.records()})   # and no record of its own
        self.assertFalse(self.j.run_path("b29f3c80").exists())

    def test_the_whole_lookback_is_asked_about_and_after_it_the_request_is_new(self):
        done = self.saved()
        for later in (ops.IDEM_WINDOW + 1, ops.ASK_WAIT, ops.APP_WAIT, ops.LOOKBACK):
            run, reply = self.start(op="b29f3c80", now=done + later)
            self.assertEqual(("asked", None), (reply and reply["state"], run), later)
        run, reply = self.start(op="b29f3c80", now=done + ops.LOOKBACK + 1)
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_a_confirmed_retry_runs(self):
        done = self.saved()
        run, reply = self.start(op="b29f3c80", now=done + 300, confirm="a19f3c80")
        self.assertIsNone(reply)
        self.assertIsNotNone(run)
        self.assertEqual("a19f3c80", self.j.latest()["b29f3c80"]["request"]["confirm"])

    def test_a_confirm_that_names_another_action_is_asked_again(self):
        done = self.saved()
        for confirm in ("c39f3c80", "", None, 7):
            run, reply = self.start(op="b29f3c80", now=done + 300, confirm=confirm)
            self.assertEqual(("asked", "a19f3c80"), (reply["state"], reply["again"]), confirm)

    def test_a_confirm_answers_only_the_latest_question(self):
        """Confirmed once, done once more; sent again with the same confirm, it
        repeats the second action now, and is asked about that one."""
        done = self.saved()
        run, _ = self.start(op="b29f3c80", now=done + 300, confirm="a19f3c80")
        run.finish("saved", REQUESTS["park"], said="Acme Review, Pricing is parked")
        run.close(REQUESTS["park"])
        later = self.j.latest()["b29f3c80"]["done"] + 300
        run, reply = self.start(op="c39f3c80", now=later, confirm="a19f3c80")
        self.assertIsNone(run)
        self.assertEqual("b29f3c80", reply["again"])

    def test_a_different_request_past_the_window_runs_as_usual(self):
        done = self.saved()
        run, reply = self.start(op="b29f3c80", now=done + 300, thread="Other")
        self.assertIsNotNone(run)
        self.assertIsNone(reply)

    def test_a_failure_is_never_asked_about(self):
        for outcome in ("refused", "crashed"):
            first, _ = self.start(op="a19f3c80")
            first.finish(outcome, REQUESTS["park"], why="a wall")
            first.close(REQUESTS["park"])
            self.runs.remove(first)
            run, reply = self.start(op="b29f3c80", now=time.time() + 300)
            self.assertIsNone(reply, outcome)
            run.close(REQUESTS["park"])
            self.runs.remove(run)
            self.j.path.unlink()

    def test_the_question_is_not_a_save_and_says_what_was(self):
        done = self.saved(said="Acme Review, Pricing is parked")
        _, reply = self.start(op="b29f3c80", now=done + 300)
        self.assertFalse(reply["ok"])
        self.assertNotIn("outcome", reply)                                    # nothing the page could read as saved
        self.assertIn("Acme Review, Pricing is parked", reply["say"])          # what the first one did, in its words
        self.assertTrue(reply["say"].endswith("?"))

    def test_confirm_is_declared_for_every_recorded_verb_and_never_part_of_the_key(self):
        for verb, req in REQUESTS.items():
            self.assertIn("confirm", ops.OPS[verb].fields, verb)
            self.assertNotIn("confirm", ops.OPS[verb].identity, verb)
            self.assertIsNone(ops.validate(verb, dict(req, confirm="a19f3c80")), verb)
            self.assertEqual(ops.identity_key(verb, req), ops.identity_key(verb, dict(req, confirm="a19f3c80")), verb)


class TestClock(unittest.TestCase):
    """#137: the window, the lookback and every client's wait, in one place
    and derived from each other, rather than three files of unrelated numbers."""

    def test_each_wait_is_derived_from_the_work_it_waits_for(self):
        self.assertEqual(2 * ops.TURN_TIMEOUT + ops.COMMIT_TIMEOUT + ops.GIT_TIMEOUT, ops.ASK_WAIT)
        self.assertGreater(ops.APP_WAIT, ops.ASK_WAIT)                      # ask.py's own message comes first
        self.assertGreaterEqual(ops.LOOKBACK, ops.APP_WAIT)                 # the retry a client that gave up invites is recognised
        self.assertLess(ops.IDEM_WINDOW, ops.LOOKBACK)

    def test_the_status_extra_takes_its_numbers_from_it(self):
        self.assertEqual((ops.GIT_TIMEOUT, ops.COMMIT_TIMEOUT), (pa.GIT_TIMEOUT, pa.COMMIT_TIMEOUT))
        for name in ("GIT_TIMEOUT", "COMMIT_TIMEOUT", "TURN_TIMEOUT", "ASK_WAIT"):
            self.assertEqual(getattr(ops, name), pa.clock(name), name)
        text = (REPO / "extras" / "status" / "ask.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?m)^(TURN_TIMEOUT|ASK_WAIT) = \d", text))   # no number of its own
        self.assertIsNone(re.search(r"(?m)^(GIT_TIMEOUT|COMMIT_TIMEOUT) = \d", (REPO / "extras" / "status" / "page_action.py")
                                    .read_text(encoding="utf-8")))

    def test_the_app_holds_a_copy_of_its_wait_and_the_copy_is_held_here(self):
        swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertEqual(float(ops.APP_WAIT), float(re.search(r"let askWait = ([\d.]+)", swift).group(1)))


class TestReader(JournalCase):
    def test_it_lists_what_is_open_and_what_ended_recently(self):
        now = time.time()
        a, _ = self.start(op="a19f3c80", now=now - 5)
        a.running()
        b, _ = self.start("wake", op="b29f3c80", now=now - 50)
        b.finish("saved", REQUESTS["wake"], said="awake")
        b.close(REQUESTS["wake"])
        old = {"op": "c39f3c80", "key": "k", "verb": "park", "zone": "Work", "state": "completed", "phase": "", "at": now - 5000,
               "done": now - 4000, "outcome": "saved", "say": "old", "label": "x", "request": {}}
        self.j.append(old)
        listed = self.j.open_set(now)
        self.assertEqual(["a19f3c80", "b29f3c80"], [r["op"] for r in listed])
        self.assertEqual(("running", None), (listed[0]["state"], listed[0]["outcome"]))
        self.assertEqual(("completed", "saved", "awake"), (listed[1]["state"], listed[1]["outcome"], listed[1]["say"]))
        self.assertTrue(all(set(r) == {"op", "verb", "zone", "state", "phase", "at", "done", "outcome", "say", "label"} for r in listed))

    def test_a_tick_lists_its_lines_for_a_reload(self):
        """#107: one record lists every line of a batch, so a reload knows which
        rows are pending; a park lists none."""
        keys = ["0123456789abcdef", "fedcba9876543210"]
        self.start("todo-done", op="a19f3c80", key=None, keys=keys)
        self.start("todo-undo", op="b29f3c80")
        self.start(op="c39f3c80")
        listed = {r["op"]: r for r in self.j.open_set()}
        self.assertEqual(keys, listed["a19f3c80"]["keys"])
        self.assertEqual(["0123456789abcdef"], listed["b29f3c80"]["keys"])
        self.assertNotIn("keys", listed["c39f3c80"])
        self.assertEqual("Ticking 2 lines…", listed["a19f3c80"]["label"])

    def test_the_reply_says_what_the_page_needs(self):
        self.start(op="a19f3c80")
        reply = ops.read(self.folder)
        self.assertEqual(True, reply["durable"])
        self.assertEqual(sorted(REQUESTS), reply["verbs"])
        self.assertEqual(["a19f3c80"], [r["op"] for r in reply["ops"]])
        self.assertIn("{zone}", reply["lost"])
        self.assertIsNone(SUCCESS.search(reply["lost"]))

    def test_a_record_with_no_worker_reads_back_unknown_and_stays_that_way(self):
        self.j.folder.mkdir(parents=True)
        queued = {"op": "a19f3c80", "key": "k", "verb": "park", "zone": "Work", "state": "running", "phase": "checking", "at": time.time(),
                  "done": None, "outcome": None, "say": None, "label": "Parking Pricing…",
                  "request": {"zone": "Work", "project": "Acme Review", "thread": "Pricing"}}
        self.j.append(queued)                                                  # and no .run file: the worker is gone
        listed = self.j.open_set()
        self.assertEqual(("failed", "unknown"), (listed[0]["state"], listed[0]["outcome"]))
        self.assertIsNone(SUCCESS.search(listed[0]["say"]))
        self.assertIn("git log -1 in Work", listed[0]["say"])
        self.assertIn("Trying again is safe", listed[0]["say"])
        self.j.open_set()                                                      # a second read does not write a second one
        self.assertEqual(2, len(self.j.records()))

    def test_a_worker_that_is_alive_is_left_alone(self):
        run, _ = self.start(op="a19f3c80")
        run.running()
        self.assertEqual("running", self.j.open_set()[0]["state"])
        self.assertEqual(2, len(self.j.records()))

    def test_a_worker_that_finished_between_the_read_and_the_check_keeps_its_own_record(self):
        run, _ = self.start(op="a19f3c80")
        run.finish("saved", REQUESTS["park"], said="parked")
        os.close(run.fd)                                                       # the lock is free, the record is terminal
        run.fd = os.open(os.devnull, os.O_RDONLY)
        self.assertEqual("saved", self.j.open_set()[0]["outcome"])
        self.assertEqual(2, len(self.j.records()))                             # queued, saved: nothing written for it

    def test_a_long_file_is_compacted_to_the_last_record_of_each_op(self):
        now = time.time()
        self.assertTrue(self.j.usable())
        for i in range(30):
            self.j.append({"op": "%08x" % i, "key": "k", "verb": "park", "zone": "Work", "state": "completed", "phase": "", "at": now,
                           "done": now, "outcome": "saved", "say": "x" * 30000, "request": {}, "label": "x"})
        self.assertGreater(self.j.path.stat().st_size, ops.COMPACT_BYTES)
        self.j.compact(now)
        self.assertEqual(30, len(self.j.records()))
        self.j.append({"op": "00000000", "key": "k", "verb": "park", "zone": "Work", "state": "failed", "phase": "", "at": now,
                       "done": now - 3 * ops.KEEP, "outcome": "refused", "say": "x" * 600000, "request": {}, "label": "x"})
        self.j.compact(now)
        self.assertNotIn("00000000", self.j.latest())                          # an ended op older than a day goes


if __name__ == "__main__":
    unittest.main()
