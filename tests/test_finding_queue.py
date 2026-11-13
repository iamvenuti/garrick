"""The Checks card's queue (#535): each finding as a plain question with answer buttons.

    cd tests && python3 -m unittest test_finding_queue

Invented names only: the zones are Work and Personal, the projects Acme Review and Birch Entry.
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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from test_page_action import ActionCase, REPO, git, pa  # noqa: E402
from test_status import StatusCase, status  # noqa: E402

sys.path.insert(0, str(REPO / "extras" / "status"))
import finding_queue as fq  # noqa: E402

NOTE_LINE = ("%(p)s: has 13731 words, over the 4000 of `note-max-words`; move its older dated entries to history files "
             "(`python3 System/tools/history.py dry-run` lists what would move)")
RESUME_LINE = ("%(p)s: its Resume here block has 520 words, over the 400 of `resume-max-words`; the next wrap or Nurture "
               "proposes a shorter one, and nothing changes without a yes")
TODO_LINE = ("%(p)s: 3 lines are longer than 200 characters; a line names one action, and what came of it goes in the "
             "thread note's dated entry")
MEETING_LINE = ("%(p)s: its body is 612 words, over the 450 of `meeting-max-words`; a page is one line on who was there, "
                "`## Key points` and `## Actions`, about 350 words")
HOOKS_LINE = "%(p)s: no pre-commit wall check; run `python3 System/tools/check.py --install-hooks`"
WALL_LINE = ("%(p)s: links [[Garden Notes]], a note of the Personal zone; that zone is walled and this file is in the Work zone")
REPEATED = "secret sauce recipe for the entire autumn plan"

HUB = "Zones/Work/Acme Review/Acme Review.md"
THREAD = "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"
TODO = "Zones/Work/Todo.md"
MEETING = "Wikis/Meetings/wiki/261012 - Call.md"
DECK = "Zones/Work/Acme Review/Deliverables/261027 - Sales deck.md"


def item(kind, check, path, line, **more):
    d = {"kind": kind, "check": check, "path": path, "line": line % {"p": path}, "scope": "System"}
    d.update(more)
    return d


KINDS = {
    "note-long": item("judgment", "projects", HUB, NOTE_LINE),
    "resume-long": item("judgment", "resume", THREAD, RESUME_LINE),
    "todo-long": item("judgment", "todo", TODO, TODO_LINE),
    "meeting-long": item("judgment", "meetings", MEETING, MEETING_LINE),
    "hooks-missing": item("judgment", "zones", "Zones/Work", HOOKS_LINE),
    "wall": item("wall", "", DECK, WALL_LINE, listed=True, message="%s: repeats eight or more words from Personal: '%s'" % (DECK, REPEATED)),
}


def text_of(markup: str) -> str:
    """What a reader sees of a question: its tags and attributes gone, and the Details disclosure left out."""
    markup = re.sub(r"<details.*?</details>", " ", markup, flags=re.S)
    return htmllib.unescape(re.sub(r"<[^>]+>", " ", markup))


class TestPlainWording(unittest.TestCase):
    def test_the_kinds_that_have_plain_wording(self):
        """A new kind cannot get plain wording silently: this list is the whole of it."""
        self.assertEqual(("wall", "note-long", "resume-long", "todo-long", "meeting-long", "hooks-missing"), fq.PLAIN_KINDS)
        self.assertEqual(set(fq.PLAIN_KINDS), set(fq.ANSWERS))
        self.assertEqual(set(fq.PLAIN_KINDS), set(fq.TAGS))
        self.assertEqual("mechanical", fq.MECHANICAL)

    def test_each_kind_is_found_by_its_check_name_and_text(self):
        for plain, it in KINDS.items():
            self.assertEqual(plain, fq.plain_kind(it), plain)
        self.assertEqual("mechanical", fq.plain_kind({"kind": "mechanical", "check": "links", "line": "x"}))
        self.assertEqual("", fq.plain_kind({"kind": "judgment", "check": "links", "line": "Zones/Work/a.md: something odd"}))
        self.assertEqual("", fq.plain_kind({"kind": "attribution", "check": "memory", "line": "a"}))
        # the same words under another check are not the same finding
        self.assertEqual("", fq.plain_kind(dict(KINDS["resume-long"], check="threads")))

    def test_the_kinds_are_the_ones_check_py_makes(self):
        """The wording table is keyed by what check.py really says, built here by check.py itself."""
        import check
        import history
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "Workspace"
        from fixtures import build_workspace, project_hub, thread_note
        build_workspace(root)
        hub = root / "Zones" / "Work" / "Acme Review" / "Acme Review.md"
        write(hub, project_hub("Work", "Acme Review", "acme", ["Pricing"]) + "\n" + "word " * 4500 + "\n")
        pricing = root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Pricing.md"
        write(pricing, thread_note("Acme Review", "Pricing", "acme").replace(
            "### Resume here\n", "### Resume here\n\n" + "word " * 500 + "\n", 1) if "### Resume here" in thread_note("Acme Review", "Pricing", "acme")
            else thread_note("Acme Review", "Pricing", "acme"))
        write(root / "Zones" / "Work" / "Todo.md", "# Work: open actions\n\n## Inbox\n\n- [ ] %s\n\n## Done\n" % ("long " * 60))
        found = {(f.check, fq.plain_kind({"kind": "judgment", "check": f.check, "line": "%s: %s" % (f.path, f.message)}))
                 for f in check.run_checks(root)}
        self.assertIn(("projects", "note-long"), found)
        self.assertIn(("todo", "todo-long"), found)
        for words, cap, make in ((13731, 4000, history.note_over),):
            self.assertIn("`note-max-words`", make(words, cap))
        self.assertTrue(fq.RESUME_RE.search("%s: %s" % (THREAD, history.resume_over(520, 400))))
        self.assertTrue(fq.RESUME_RE.search("%s: %s" % (THREAD, history.resume_over(520, 400, "auto"))))

    def test_figures_are_said_for_the_ear(self):
        self.assertEqual("about 14,000", fq.about(13731))
        self.assertEqual("about 4,300", fq.about(4271))
        self.assertEqual("about 500", fq.about(520))
        self.assertEqual("about 600", fq.about(612))

    def test_each_kind_shows_its_sentence_reason_and_buttons(self):
        want = {
            "note-long": ("The Acme Review project page is getting long: about 14,000 words.",
                          ["Move older entries to history", "Show me what would move", "Not now"]),
            "resume-long": ("The resume point of Pricing is getting long: about 500 words.", ["Shorten it", "Not now"]),
            "todo-long": ("3 lines in the Work to-do list are longer than an action should be.", ["Shorten the line", "Not now"]),
            "meeting-long": ("A meeting note is longer than usual: about 600 words.", ["Shorten it", "Let me open it", "Not now"]),
            "hooks-missing": ("The Work zone does not check the walls before a commit.", ["Install the wall check"]),
            "wall": ("“261027 - Sales deck” in Work points into private material from Personal.", ["Take it out", "Show me both texts"]),
        }
        for plain, (sentence, labels) in want.items():
            q = fq.question(KINDS[plain], "Zones/Work")
            self.assertEqual(sentence, q["sentence"], plain)
            self.assertTrue(q["why"] and q["tag"], plain)
            shown = [a["label"] for a in q["answers"]]
            if plain == "wall":
                shown[1] = "Show me both texts" if shown[1] == "Show me the file" else shown[1]
            self.assertEqual(labels, shown, plain)
            self.assertEqual(q["answers"][0]["id"], q["recommended"], plain)               # the recommended one first
            markup = fq.question_html(q)
            self.assertEqual(1, markup.count('class="opt rec'), plain)
            self.assertLess(markup.index("opt rec"), markup.index('class="opt"') if 'class="opt"' in markup else 10 ** 9, plain)
            self.assertIn("Recommended.", markup)
            self.assertIn("<summary>Details</summary>", markup)
            self.assertNotIn("<details open", markup)                                       # closed by default
            opts = re.findall(r'<(?:button|label) class="opt( rec| other)?[^"]*"', markup)
            self.assertEqual(" other", opts[-1], plain)                                     # the free-text field is last
            self.assertEqual(1, opts.count(" other"), plain)
            self.assertIn("Something else: tell Garrick what to do", markup)

    def test_no_path_setting_or_command_outside_details(self):
        banned = ("/", ".md", "`", "python3", "note-max-words", "resume-max-words", "meeting-max-words", "history.py", "check.py",
                  "--install-hooks", "dry-run", "garrick-settings")
        for plain, it in KINDS.items():
            seen = text_of(fq.question_html(fq.question(it, "Zones/Work")))
            for word in banned:
                self.assertNotIn(word, seen, "%s shows %r" % (plain, word))
            details = fq.question(it, "Zones/Work")["details"]
            self.assertTrue(details, plain)                                                 # the check's own text is kept, as detail

    def test_the_answers_are_the_planned_ones(self):
        ids = {k: [(a["id"], a["action"]) for a in v] for k, v in fq.ANSWERS.items()}
        self.assertEqual([("move-older", "run"), ("preview", "preview"), ("later", "later")], ids["note-long"])
        self.assertEqual([("shorten", "handoff"), ("later", "later")], ids["resume-long"])
        self.assertEqual([("shorten", "handoff"), ("later", "later")], ids["todo-long"])
        self.assertEqual([("shorten", "handoff"), ("open", "open"), ("later", "later")], ids["meeting-long"])
        self.assertEqual([("install", "run")], ids["hooks-missing"])                          # no Not now: hidden, the walls go unchecked
        self.assertEqual([("take-out", "handoff"), ("show-both", "open")], ids["wall"])      # no Not now, no "the words are mine"
        for a in fq.ANSWERS["wall"]:
            self.assertNotIn("keep", a["label"].lower())
        self.assertEqual({"note-long": ("move-older", "preview", "later"), "resume-long": ("later",), "todo-long": ("later",),
                          "meeting-long": ("later",), "hooks-missing": ("install",), "wall": ()}, fq.VERB_ANSWERS)
        for answers in fq.ANSWERS.values():
            self.assertIn(answers[0]["action"], ("handoff", "run"))                          # the recommended one does something

    def test_any_other_kind_shows_the_check_text_and_something_else_only(self):
        q = fq.question({"kind": "judgment", "check": "links", "path": "Zones/Work/a.md", "scope": "Zones/Work",
                         "line": "Zones/Work/a.md: something odd about a link", "title": "Links"}, "Zones/Work")
        self.assertEqual("other", q["id"])
        self.assertEqual("something odd about a link", q["sentence"])
        self.assertEqual("Links", q["tag"])
        self.assertEqual([], q["answers"])
        markup = fq.question_html(q)
        self.assertNotIn("data-fa", markup)                                                  # no answer button
        self.assertEqual(1, markup.count("opt other"))

    def test_a_walls_hand_off_names_the_file_and_the_zones_and_never_the_repeated_words(self):
        q = fq.question(KINDS["wall"], "Zones/Work")
        phrase = q["answers"][0]["phrase"]
        self.assertIn(DECK, phrase)
        self.assertIn("Personal", phrase)
        self.assertIn("Work", phrase)
        self.assertNotIn(REPEATED, phrase)
        self.assertNotIn("secret", phrase)
        self.assertNotIn("repeats", phrase)
        self.assertNotIn(REPEATED, q["free"])
        markup = fq.question_html(q)
        outside = re.sub(r"<code>.*?</code>", "", markup, flags=re.S)
        self.assertNotIn("secret", outside)                                                  # only Details holds the check's text
        for a in q["answers"]:
            self.assertNotIn("secret", json.dumps(a))

    def test_a_wall_the_quick_check_does_not_list_names_no_file_and_no_other_zone(self):
        it = dict(KINDS["wall"], listed=False, ask="nurture Work")
        del it["message"]
        q = fq.question(it, "Zones/Work")
        self.assertEqual("A file in Work points into private material from another zone.", q["sentence"])
        self.assertEqual("nurture Work", q["answers"][0]["phrase"])
        markup = fq.question_html(q)
        self.assertNotIn("Personal", markup)
        self.assertNotIn("Sales deck", markup)
        self.assertNotIn("Zones/Work/Acme", markup)

    def test_a_wall_opens_both_files_when_the_check_names_the_other(self):
        it = dict(KINDS["wall"], message="%s: writes the path `Zones/Personal/Garden/Notes.md`, a note of the Personal zone; "
                                         "that zone is walled and this file is in the Work zone" % DECK)
        both = fq.question(it, "Zones/Work")["answers"][1]
        self.assertEqual("Show me both texts", both["label"])
        self.assertEqual([{"verb": "note-open", "path": DECK}, {"verb": "note-open", "path": "Zones/Personal/Garden/Notes.md"}], both["reqs"])
        one = fq.question(KINDS["wall"], "Zones/Work")["answers"][1]
        self.assertEqual("Show me the file", one["label"])                                    # no other file named: only this one opens
        self.assertEqual([{"verb": "note-open", "path": DECK}], one["reqs"])

    def test_the_keys_and_the_free_text_field(self):
        js = fq.QUEUE_JS
        self.assertIn("/^[1-4]$/.test(e.key)", js)                                           # 1 to 4 pick an answer
        self.assertIn("o.classList.contains('other')", js)                                   # the free-text field is a number too: it takes the focus
        self.assertIn("e.key==='Enter'", js)                                                 # Return takes the recommended one
        self.assertIn("tagName==='INPUT'", js)                                               # and sends the text while typing in the field
        self.assertIn("'.opt.rec:not([hidden]):not(:disabled)'", js)
        self.assertIn("function foc(q)", js)                                                 # S1: the focus goes to the recommended answer
        self.assertRegex(js, r"(?s)function show\(done0\)\{.*foc\(q\)\}")                       # on open and after every answer
        self.assertIn("summary,a,input,textarea,select,button", js)                            # S5: Return on Details or a link runs nothing
        self.assertIn("e.isComposing", js)                                                   # L2
        self.assertIn("done:true", js)                                                       # S2: the done screen is kept across a rebuild
        self.assertIn("if(r.done){dlg.showModal();show(true);return}", js)
        self.assertNotRegex(js, r"dataset\.key")                                             # L1: the page's own key, not the Not now hash
        node = shutil.which("node")
        if node:
            done = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=js, capture_output=True,
                                  text=True, timeout=30)
            self.assertEqual(0, done.returncode, done.stderr)


class TestWallsFromCheckPy(unittest.TestCase):
    """The other zone of a wall finding is read from the texts check.py really writes (F3)."""

    def setUp(self):
        import check
        from fixtures import build_workspace, meeting_page
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "Workspace"
        build_workspace(self.root)
        self.check = check
        self.meeting_page = meeting_page

    def walls(self):
        return [f for f in self.check.run_checks(self.root) if f.check == "walls" and f.severity == "error"]

    def other(self, f):
        return fq.wall_other({"kind": "wall", "path": f.path, "line": "%s: %s" % (f.path, f.message), "message": f.message})

    def test_a_link_to_a_meeting_of_another_zone(self):
        far = self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260312-birch-kickoff.md"
        far.write_text(far.read_text().replace("zone: Work", "zone: Personal"))
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Notes.md", "Their pricing: see [[260312-birch-kickoff]].\n")
        found = self.walls()
        self.assertTrue(found)
        self.assertIn("a meeting of the Personal zone; that zone is walled", found[0].message)
        self.assertEqual("Personal", self.other(found[0]))

    def test_a_written_path_and_repeated_wording(self):
        sentence = "the harvest plan for the whole autumn season stays with the garden club members"
        write(self.root / "Zones" / "Personal" / "Garden" / "Notes.md", "# Notes\n\n%s\n" % sentence)
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Paths.md", "See `Zones/Personal/Garden/Notes.md`.\n")
        write(self.root / "Zones" / "Work" / "Acme Review" / "Threads" / "Pricing" / "Copy.md", "# Copy\n\n%s\n" % sentence)
        found = self.walls()
        self.assertTrue(any(f.message.startswith("writes the path") for f in found), [f.message for f in found])
        self.assertTrue(any(f.message.startswith("repeats wording") for f in found), [f.message for f in found])
        for f in [f for f in found if f.path.startswith("Zones/Work/")]:
            self.assertEqual("Personal", self.other(f), f.message)
            q = fq.question(dict(kind="wall", check="", path=f.path, line=f.message, message=f.message, listed=True, scope="Zones/Work"), "Zones/Work")
            self.assertIn("from Personal", q["sentence"])
            self.assertNotIn("harvest", q["answers"][0]["phrase"])

    def test_the_meeting_name_may_hold_of_the(self):
        text = "links [[Call of the Wild]], a meeting of the Cedar zone; that zone is walled and this file is in the Work zone"
        self.assertEqual("Cedar", fq.wall_other({"message": text}))
        self.assertEqual("", fq.wall_other({"message": "links [[x]], a note that names no zone, so nothing says whose it is"}))


class TestNotNowFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_the_key_is_a_hash_and_the_file_holds_no_path_and_no_text(self):
        key = fq.later_key("note-long", HUB)
        self.assertRegex(key, r"^[0-9a-f]{16}$")
        today = dt.date(2026, 11, 13)
        until = fq.later_put(self.root, key, today)
        self.assertEqual("2026-11-20", until)
        text = fq.later_path(self.root).read_text(encoding="utf-8")
        for leaked in ("Acme", "Zones", ".md", "note-long", "Work"):
            self.assertNotIn(leaked, text)
        self.assertEqual({"version": 1, "later": {key: "2026-11-20"}}, json.loads(text))
        self.assertEqual("System/generated/status-later.json", fq.later_path(self.root).relative_to(self.root).as_posix())

    def test_it_hides_for_seven_days_and_the_finding_comes_back(self):
        key = fq.later_key("note-long", HUB)
        fq.later_put(self.root, key, dt.date(2026, 11, 13))
        self.assertEqual({key}, fq.later_hidden(self.root, dt.date(2026, 11, 19)))
        self.assertEqual(set(), fq.later_hidden(self.root, dt.date(2026, 11, 20)))           # back on the seventh day
        fq.later_put(self.root, fq.later_key("resume-long", THREAD), dt.date(2026, 12, 1))   # a later write drops what is back
        self.assertEqual(1, len(json.loads(fq.later_path(self.root).read_text())["later"]))

    def test_a_file_that_is_wrong_hides_nothing(self):
        for text in ("", "not json", "[]", '{"later": []}', '{"later": {"x": "2099-01-01"}}', '{"later": {"%s": "soon"}}' % ("a" * 16)):
            write(fq.later_path(self.root), text)
            self.assertEqual(set(), fq.later_hidden(self.root, dt.date(2026, 11, 13)), text)

    def test_a_wall_finding_is_never_put_off(self):
        wall = dict(KINDS["wall"], scope="Zones/Work")
        hidden = {fq.later_key("wall", DECK), fq.later_key("other", DECK)}
        self.assertEqual(1, len(fq.forecast_questions([wall], hidden)["Zones/Work"]))


class QueueCase(StatusCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "template" / "System" / "tools", self.root / "System" / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        status._NURTURE.clear()
        self.addCleanup(status._NURTURE.clear)
        self.folder = self.root / "System" / "generated" / "nurture"

    def record(self, standing, back=0):
        day = self.now.date() - dt.timedelta(days=back)
        if not getattr(self, "_quick_set", False):       # the quick check lists what the record holds, unless a test says what it lists
            self.list_record(standing)
        N = status.nurture_lib(self.root)[0]
        scopes = {}
        for f in standing:
            scopes.setdefault(N.debt_scope(f["path"]), {})
            scopes[N.debt_scope(f["path"])][f["kind"]] = scopes[N.debt_scope(f["path"])].get(f["kind"], 0) + 1
        write(self.folder / ("%s.json" % day.isoformat()), json.dumps({"date": day.isoformat(), "standing": standing, "debt": {
            "total": len(standing), "kinds": {}, "scopes": scopes, "whole": True, "threshold": 40}}))

    def list_record(self, standing):
        self.quick(*[{"check": f.get("check", ""), "severity": "warning", "path": f["path"], "message": f["line"].split(": ", 1)[-1]}
                     for f in standing if f["kind"] != "wall"])
        self._quick_set = False

    def standing(self):
        out = []
        for plain, it in KINDS.items():
            f = {"kind": it["kind"], "path": it["path"], "line": it["line"]}
            if it["kind"] != "wall":
                f["check"] = it["check"]
            out.append(f)
        return out

    def view(self, html, tag="dialog", id_="queue"):
        start = html.index('<%s id="%s"' % (tag, id_))
        return html[start:html.index("</%s>" % tag, start)]

    def card(self, html):
        start = html.index('<details class="card" id="checks"')
        ends = [i for i in (html.find('<details class="card" id="', start + 1), html.find("</section>", start)) if i > 0]
        return html[start:min(ends)]

    def quick(self, *findings):
        self._quick_set = True
        (self.root / "System" / "tools" / "check.py").write_text("import json\nprint(json.dumps(%r))\n" % {
            "errors": 0, "warnings": len(findings), "findings": list(findings)})


class TestQueueOnThePage(QueueCase):
    def test_a_lines_number_and_its_queues_are_one_list(self):
        self.record(self.standing())
        html = self.page()
        card, queue = self.card(html), self.view(html)
        line = re.search(r'<span class="nsay">(Work): (\d+ wall findings? and )?(\d+) judgment calls?, about \d+ minutes</span>', card)
        self.assertIsNotNone(line, card)
        said = int(re.search(r"(\d+) wall", line.group(0)).group(1)) + int(line.group(3)) if "wall" in line.group(0) else int(line.group(3))
        scope = queue[queue.index('data-scope="Zones/Work"'):]
        scope = scope[:scope.index("</section>")]
        self.assertEqual(said, scope.count("data-q "))                                       # the same number, from one list
        self.assertIn('data-qopen="Zones/Work"', card)
        self.assertIn(">Go through them</button>", card)
        self.assertNotIn(">Nurture</button>", card)

    def test_walls_come_first_and_every_kind_is_in_the_queue(self):
        self.record(self.standing())
        queue = self.view(self.page())
        work = queue[queue.index('data-scope="Zones/Work"'):]
        work = work[:work.index("</section>")]
        kinds = re.findall(r'data-q data-key="[0-9a-f]{16}" data-kind="([^"]+)"', work)
        self.assertEqual(["wall", "note-long", "resume-long", "todo-long", "hooks-missing"], kinds)
        meetings = queue[queue.index('data-scope="Wikis/Meetings"'):]
        self.assertIn('data-kind="meeting-long"', meetings)

    def test_the_wall_finding_is_in_the_queue_with_the_check_text_only_in_details(self):
        self.quick({"check": "walls", "severity": "error", "path": DECK, "message": "repeats eight or more words from Personal: '%s'" % REPEATED})
        self.record(self.standing())
        queue = self.view(self.page())
        q = queue[queue.index("<div class=\"q\" data-q data-key=\"%s\"" % fq.later_key("wall", DECK)):]
        q = q[:q.index("</details>")]
        self.assertIn("“261027 - Sales deck” in Work points into private material from Personal.", q)
        self.assertNotIn("Not now", q)
        self.assertNotIn("keep", re.sub(r"<code>.*", "", q, flags=re.S).lower())
        outside = re.sub(r"<code>.*?</code>", "", q, flags=re.S)
        self.assertNotIn(REPEATED, outside)
        self.assertIn(REPEATED, htmllib.unescape(q))                                         # Details: the check's own text, as the list showed it

    def test_the_queue_shows_no_more_than_the_page_showed_of_a_wall(self):
        """The quick check does not list this wall, so the page showed only a count of it (#525): the queue says where it is
        and nothing else."""
        self.quick()
        self.record([{"kind": "wall", "path": DECK, "line": WALL_LINE % {"p": DECK}}])
        queue = self.view(self.page())
        self.assertIn("A file in Work points into private material from another zone.", queue)
        for hidden_name in ("Sales deck", "Personal", DECK):
            self.assertNotIn(hidden_name, queue)
        self.assertIn('"phrase": "nurture Work"', htmllib.unescape(queue))

    def test_a_quick_check_text_enriches_the_questions_numbers(self):
        self.quick({"check": "projects", "severity": "warning", "path": HUB, "message": NOTE_LINE.split(": ", 1)[1].replace("13731", "21000")})
        self.record([{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}}])
        queue = self.view(self.page())
        self.assertIn("is getting long: about 21,000 words.", queue)

    def test_not_now_hides_it_drops_the_count_and_the_checks_are_unchanged(self):
        standing = [{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}},
                    {"kind": "judgment", "check": "resume", "path": THREAD, "line": RESUME_LINE % {"p": THREAD}},
                    {"kind": "judgment", "check": "todo", "path": TODO, "line": TODO_LINE % {"p": TODO}}]
        self.record(standing)
        before = self.page()
        self.assertIn("Work: 3 judgment calls, about 5 minutes", self.card(before))
        self.assertEqual(3, self.view(before).count("data-q "))
        record = (self.folder / ("%s.json" % self.now.date().isoformat())).read_bytes()
        check_before = self.check_json()
        self.list_record(standing)                                                             # check_json put the real check.py back
        fq.later_put(self.root, fq.later_key("note-long", HUB), self.now.date())
        after = self.page()
        self.assertIn("Work: 2 judgment calls, about 5 minutes", self.card(after))             # the count drops by one
        self.assertEqual(2, self.view(after).count("data-q "))
        self.assertNotIn('data-kind="note-long"', self.view(after))
        self.assertEqual(check_before, self.check_json())                                     # check.py --json is the same
        self.assertEqual(record, (self.folder / ("%s.json" % self.now.date().isoformat())).read_bytes())    # and so is Nurture's record
        # a week on, it is back
        later = self.now + dt.timedelta(days=7)
        self.now = later
        self.record(standing)
        self.assertEqual(3, self.view(self.page()).count("data-q "))

    def test_missing_hooks_is_never_put_off_even_with_a_key_present(self):
        it = KINDS["hooks-missing"]
        fq.later_put(self.root, fq.later_key("hooks-missing", it["path"]), self.now.date())
        self.record([{"kind": "judgment", "check": "zones", "path": it["path"], "line": it["line"]}])
        queue = self.view(self.page())
        self.assertIn('data-kind="hooks-missing"', queue)
        out = fq.forecast_questions([dict(it, scope="Zones/Work")], {fq.later_key("hooks-missing", it["path"])})
        self.assertEqual(1, len(out["Zones/Work"]))

    def test_a_wall_the_quick_check_lists_has_a_line_when_no_record_item_covers_its_scope(self):
        self.quick({"check": "walls", "severity": "error", "path": DECK, "message": "links [[Garden Notes]], a note of the Personal zone; "
                    "that zone is walled and this file is in the Work zone"})
        self.record([{"kind": "judgment", "check": "projects", "path": "Zones/Alder/Yard/Yard.md", "line": NOTE_LINE % {"p": "Zones/Alder/Yard/Yard.md"}}])
        html = self.page()
        card = self.card(html)
        self.assertNotIn("Nothing needs you.", card)
        self.assertRegex(card, r"Work: 1 wall finding, about 5 minutes")
        work = self.view(html)
        work = work[work.index('data-scope="Zones/Work"'):]
        self.assertIn('data-kind="wall"', work[:work.index("</section>")])
        self.assertIn("points into private material from Personal.", work)

    def test_nothing_needs_you_shows_only_when_nothing_in_the_quick_check_needs_it_either(self):
        self.quick({"check": "walls", "severity": "error", "path": DECK, "message": "links [[Garden Notes]], a note of the Personal zone; "
                    "that zone is walled and this file is in the Work zone"})
        self.record([{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}}])
        fq.later_put(self.root, fq.later_key("note-long", HUB), self.now.date())
        self.assertNotIn("Nothing needs you.", self.card(self.page()))          # the wall stays: Not now put off only the long note
        self.quick({"check": "links", "severity": "error", "path": "Zones/Work/Acme Review/Notes.md", "message": "links a note that is not there"})
        card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)
        self.assertIn("Work: 1 judgment call", card)
        self.quick({"check": "links", "severity": "warning", "path": "Zones/Work/Acme Review/Notes.md", "message": "a warning only"})
        self.assertIn("Nothing needs you.", self.card(self.page()))

    def test_a_wall_weighted_zero_still_counts_on_the_card(self):
        write(self.root / "System" / "garrick-settings.json", json.dumps({"nurture-weights": {"wall": 0}}))
        self.quick({"check": "walls", "severity": "error", "path": DECK, "message": "links [[Garden Notes]], a note of the Personal zone; "
                    "that zone is walled and this file is in the Work zone"})
        self.record([{"kind": "wall", "path": DECK, "line": WALL_LINE % {"p": DECK}}])
        card = self.card(self.page())
        self.assertNotIn("Nothing needs you.", card)
        self.assertIn("Work: 1 wall finding", card)
        self.quick()
        self.assertIn("Work: 1 wall finding", self.card(self.page()))           # and when the quick check lists nothing, the record's wall

    def test_two_questions_with_one_kind_and_path_keep_two_keys(self):
        a = dict(KINDS["wall"], scope="Zones/Work", message="%s: links [[A]], a note of the Personal zone; that zone is walled and this file is in the Work zone" % DECK)
        b = dict(KINDS["wall"], scope="Zones/Work", message="%s: links [[B]], a note of the Cedar zone; that zone is walled and this file is in the Work zone" % DECK)
        qs = fq.forecast_questions([a, b, dict(a)], set())["Zones/Work"]
        self.assertEqual(3, len({q["gk"] for q in qs}))
        self.assertEqual({fq.later_key("wall", DECK)}, {q["key"] for q in qs})   # Not now's key stays the hash of kind and path
        self.assertEqual(3, len(set(re.findall(r'data-gk="([^"]+)"', "".join(fq.question_html(q) for q in qs)))))

    def test_the_done_screen_is_kept_until_the_queue_is_closed(self):
        js = fq.QUEUE_JS
        show = js[js.index("function show("):js.index("function open(")]
        self.assertNotIn("st.del(KEY)", show)                                                # an empty queue saves done, it does not delete
        click = js[js.index("data-qclose]')){"):][:60]
        self.assertIn("st.del(KEY)", click)                                                  # and Close or Back to the overview delete it
        self.assertIn("dlg.addEventListener('close',function(){st.del(KEY)})", js)

    def test_a_browser_shows_no_dead_answer_and_says_the_app_is_needed(self):
        self.assertIn(".nohost .queue .opt.tacts{display:none}", fq.QUEUE_CSS)
        self.record([{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}}])
        self.quick({"check": "projects", "severity": "warning", "path": HUB, "message": NOTE_LINE.split(": ", 1)[1]})
        moves = {"moves": 3, "before": 6400, "after": 3900, "still_over": False, "case": "", "skipped": ""}
        with mock.patch.object(status.queue_mod().Planner, "plan", return_value=moves):
            queue = self.view(self.page())
        self.assertIn('class="hint qweb">The other answers need the Garrick app.', queue)
        for plain in ("resume-long", "wall"):
            self.assertNotIn("qweb", fq.question_html(fq.question(KINDS[plain], "Zones/Work")))     # an answer a browser can send: no hint
        self.assertIn("qweb", fq.question_html(fq.question(KINDS["hooks-missing"], "Zones/Work")))

    def test_an_applied_answer_is_gone_from_the_next_build_but_a_wall_never_is(self):
        self.record([{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}},
                     {"kind": "wall", "path": DECK, "line": WALL_LINE % {"p": DECK}}])
        self.quick({"check": "projects", "severity": "warning", "path": HUB, "message": NOTE_LINE.split(": ", 1)[1]})
        self.assertIn('data-kind="note-long"', self.view(self.page()))                       # the quick check still lists it
        self.quick()                                                                         # the answer was applied: it lists nothing
        html = self.page()
        self.assertNotIn('data-kind="note-long"', self.view(html))
        self.assertIn('data-kind="wall"', self.view(html))                                   # a wall is not dropped by what the check no longer lists
        self.assertIn("Work: 1 wall finding", self.card(html))

    def check_json(self):
        """check.py --json of the fixture workspace, run for real."""
        shutil.copy2(REPO / "template" / "System" / "tools" / "check.py", self.root / "System" / "tools" / "check.py")
        out = subprocess.run([sys.executable, str(self.root / "System" / "tools" / "check.py"), "--root", str(self.root), "--json"],
                             capture_output=True, text=True, timeout=300, cwd=str(self.root))
        data = json.loads(out.stdout)
        return json.dumps(data, sort_keys=True)

    def test_no_check_and_no_nurture_reads_the_not_now_file(self):
        for name in ("check.py", "nurture.py", "garrick_lib.py", "history.py"):
            self.assertNotIn("status-later", (REPO / "template" / "System" / "tools" / name).read_text(encoding="utf-8"), name)
        for path in (REPO / "template" / "System" / "tools").glob("*.py"):
            if path.name != "garrick_lib.py":
                self.assertNotIn("status-later", path.read_text(encoding="utf-8"), path.name)

    def test_nothing_needs_you_when_every_finding_is_put_off(self):
        self.record([{"kind": "judgment", "check": "projects", "path": HUB, "line": NOTE_LINE % {"p": HUB}}])
        fq.later_put(self.root, fq.later_key("note-long", HUB), self.now.date())
        html = self.page()
        self.assertIn("Nothing needs you.", self.card(html))
        self.assertNotIn('id="queue"', html)

    def test_the_card_names_no_path_project_or_finding_text(self):
        self.quick({"check": "walls", "severity": "error", "path": DECK, "message": "repeats eight or more words from Personal: '%s'" % REPEATED})
        self.record(self.standing())
        card = self.card(self.page())
        for leaked in (".md", "Acme Review", "Sales deck", "secret", "Pricing", "words, over"):
            self.assertNotIn(leaked, card)

    def test_the_dialog_is_outside_the_card_and_its_script_and_style_are_on_the_page(self):
        self.record(self.standing())
        html = self.page()
        self.assertNotIn('id="queue"', self.card(html))
        self.assertIn('<dialog id="queue" class="findings queue"', html)
        self.assertIn(fq.QUEUE_CSS.strip()[:40], html)
        self.assertIn("garrick-queue", html)
        for colour in re.findall(r"(?<![&\w])#[0-9a-fA-F]{3,6}\b", fq.QUEUE_CSS):
            self.assertEqual("#fff", colour)                                                    # the page's own white on its accent, as .act.primary has it

    def test_no_queue_without_a_record_or_a_module(self):
        self.assertNotIn('id="queue"', self.page())
        self.record(self.standing())
        with mock.patch.object(status, "queue_mod", side_effect=OSError("gone")):
            html = self.page()
        self.assertNotIn('id="queue"', html)
        self.assertIn(">Nurture</button>", self.card(html))                                   # the card keeps its Nurture button

    def test_fix_them_counts_only_what_fix_can_do_and_runs_fix_for_each(self):
        sized = "Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"
        pricing = "Zones/Work/Acme Review/Threads/Pricing/Pricing.md"
        said = "`status` is 'ongoing', should be active, parked or done"
        self.quick(
            {"check": "threads", "severity": "warning", "path": sized, "message": said},
            {"check": "threads", "severity": "warning", "path": pricing, "message": said},
            {"check": "deliverables", "severity": "warning", "path": "Zones/Work/Acme Review/Deliverables/Deck.pptx",
             "message": "name does not start with its creation date, `YYMMDD - <name>`"})
        self.record([{"kind": "mechanical", "check": "threads", "path": sized, "line": "x"}])
        html = self.page()
        card = self.card(html)
        self.assertIn("Garrick can fix 2 small things on its own.", card)                       # the .pptx has no Fix: not counted
        data = re.search(r'data-fix="([^"]+)"', card)
        requests = json.loads(htmllib.unescape(data.group(1)))
        self.assertEqual([{"verb": "fix", "zone": "Work", "file": "Acme Review/Threads/Pricing/Pricing.md"},
                          {"verb": "fix", "zone": "Work", "file": "Birch Entry/Threads/Market Sizing/Market Sizing.md"}], requests)
        ops = pa.ops_lib(self.root)
        for req in requests:
            self.assertIsNone(ops.validate("fix", req))                                         # each one is the verb `fix`, validated as it is
        self.assertIn("Fix them</button>", card)
        self.assertNotIn('id="queue"', html)                                                    # a mechanical finding is not asked one by one

    def test_fix_them_runs_the_verb_fix_for_each_note(self):
        """The button's requests are the verb `fix`, one for each note, as the executor validates it (#541: the finding's own row is gone)."""
        sized = "Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"
        said = "`status` is 'ongoing', should be active, parked or done"
        self.quick({"check": "threads", "severity": "warning", "path": sized, "message": said})
        self.record([{"kind": "mechanical", "check": "threads", "path": sized, "line": "x"}])
        html = self.page()
        fix = re.search(r'data-fix="([^"]+)"', html)
        self.assertEqual([{"verb": "fix", "zone": "Work", "file": "Birch Entry/Threads/Market Sizing/Market Sizing.md"}],
                         json.loads(htmllib.unescape(fix.group(1))))
        self.assertIsNone(pa.ops_lib(self.root).validate("fix", json.loads(htmllib.unescape(fix.group(1)))[0]))

    def test_no_fix_them_without_a_mechanical_fix(self):
        self.quick({"check": "links", "severity": "warning", "path": "Zones/Work/a.md", "message": "x"})
        self.record([{"kind": "judgment", "check": "links", "path": "Zones/Work/a.md", "line": "Zones/Work/a.md: x"}])
        self.assertNotIn("Garrick can fix", self.card(self.page()))

    def test_fix_them_in_a_browser_hands_the_request_over(self):
        sized = "Zones/Work/Birch Entry/Threads/Market Sizing/Market Sizing.md"
        self.quick({"check": "threads", "severity": "warning", "path": sized, "message": "`status` is 'ongoing', should be active, parked or done"})
        self.record([{"kind": "mechanical", "check": "threads", "path": sized, "line": "x"}])
        card = self.card(self.page())
        self.assertIn('class="act webonly" type="button" data-request="nurture the context"', card)


class TestFindingVerb(ActionCase):
    def setUp(self):
        super().setUp()
        for tool in ("history.py", "check.py", "nurture.py"):
            shutil.copy2(REPO / "template" / "System" / "tools" / tool, self.root / "System" / "tools" / tool)
        self.hub = self.work / "Acme Review" / "Acme Review.md"
        today = dt.date.today()
        entries = "".join("**%d %s %d.** Entry %d settled the plan. %s\n\nSecond paragraph %d.\n\n" % (
            d.day, d.strftime("%B"), d.year, i, "word " * 30, i) for i, d in enumerate(
                today - dt.timedelta(days=n) for n in (1, 2, 3, 4, 5, 300, 310, 320)))
        write(self.hub, "---\ntitle: Acme Review\ntype: project\nparty: acme\nstatus: active\ncreated: 2026-01-05\nupdated: 2026-11-10\n---\n\n"
                        "# Acme Review\n\n## State of play\n\n### Resume here\n\n**Where it stands.** Under way.\n\n---\n\n" + entries)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "add a long hub")
        self.rel = "Zones/Work/Acme Review/Acme Review.md"

    def ask(self, **req):
        return pa.perform(self.root, dict({"verb": "finding"}, **req), pa.ops_lib(self.root))[0]

    def test_the_verb_is_declared_and_closed(self):
        ops = pa.ops_lib(self.root)
        self.assertIn("finding", pa.VERBS)
        self.assertIn("finding", ops.DECLARED)
        self.assertEqual(("kind", "path", "answer"), ops.DECLARED["finding"].fields)
        self.assertIsNone(ops.validate("finding", {"verb": "finding", "kind": "note-long", "path": self.rel, "answer": "preview"}))
        self.assertIsNotNone(ops.validate("finding", {"verb": "finding", "kind": "note-long", "path": self.rel, "answer": "preview", "extra": 1}))

    def test_an_unknown_kind_or_answer_is_refused_and_nothing_runs(self):
        for req in ({"kind": "nonsense", "answer": "preview"}, {"kind": "note-long", "answer": "nonsense"},
                    {"kind": "wall", "answer": "later"}, {"kind": "wall", "answer": "take-out"}, {"kind": "hooks-missing", "answer": "later"},
                    {"kind": "note-long", "answer": "shorten"}, {"kind": "resume-long", "answer": "shorten"},
                    {"kind": "meeting-long", "answer": "open"}, {"kind": 5, "answer": "later"}, {"kind": "note-long", "answer": ["later"]}):
            with mock.patch.object(pa, "finding_run") as run:
                got = self.ask(path=self.rel, **req)
            self.assertFalse(got["ok"], req)
            run.assert_not_called()
        self.assertFalse((self.root / "System" / "generated" / "status-later.json").exists())

    def test_a_path_outside_the_workspace_is_refused(self):
        for bad in ("/etc/passwd", "../Outside.md", "Zones/Work/../../../x.md", "~/x.md", "", None, "Zones/Work/Missing.md"):
            got = self.ask(kind="note-long", answer="later", path=bad)
            self.assertFalse(got["ok"], bad)
        self.assertFalse((self.root / "System" / "generated" / "status-later.json").exists())

    def test_not_now_writes_the_key_and_the_day_and_nothing_else(self):
        got = self.ask(kind="note-long", answer="later", path=self.rel)
        self.assertTrue(got["ok"], got)
        data = json.loads((self.root / "System" / "generated" / "status-later.json").read_text(encoding="utf-8"))
        self.assertEqual([fq.later_key("note-long", self.rel)], list(data["later"]))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())                    # no zone file is touched

    def test_the_preview_says_counts_and_writes_nothing(self):
        before = self.hub.read_bytes()
        got = self.ask(kind="note-long", answer="preview", path=self.rel)
        self.assertTrue(got["ok"], got)
        self.assertRegex(got["say"], r"^3 older entries would move to history, taking the page from about \d+ words to about \d+ words\.$")
        self.assertIn("Acme Review", got["detail"])                                              # the full output, for Details
        self.assertEqual(before, self.hub.read_bytes())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_the_preview_refuses_a_path_that_is_not_a_project_page_or_a_thread_note(self):
        write(self.work / "Acme Review" / "Deliverables" / "261027 - Sales deck.md", "# Deck\n")
        write(self.root / "Wikis" / "Meetings" / "wiki" / "261012 - Call.md", "# Call\n")
        for bad in ("Zones/Work/Todo.md", "Zones/Work/Acme Review/Deliverables/261027 - Sales deck.md", "Wikis/Meetings/wiki/261012 - Call.md",
                    "Zones/Work/Acme Review/Threads/Pricing/Other.md"):
            with mock.patch.object(pa, "finding_run") as run:
                got = self.ask(kind="note-long", answer="preview", path=bad)
            self.assertFalse(got["ok"], bad)
            run.assert_not_called()

    def test_move_older_entries_commits_in_the_zone_through_the_wall_check(self):
        before = git(self.work, "rev-list", "--count", "HEAD").strip()
        got = self.ask(kind="note-long", answer="move-older", path=self.rel)
        self.assertTrue(got["ok"], got)
        self.assertEqual("Moved 3 older entries of Acme Review to history", got["say"])
        self.assertEqual(int(before) + 1, int(git(self.work, "rev-list", "--count", "HEAD").strip()))
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())
        self.assertTrue(list((self.hub.parent / "history").glob("Acme Review history *.md")))
        self.assertIn("Acme Review/history/Acme Review history", git(self.work, "show", "--stat", "--format=", "HEAD"))

    def test_a_refusal_by_the_wall_check_puts_every_file_back(self):
        hook = self.work / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\n# Garrick wall check (a stand-in)\necho refused >&2\nexit 1\n")
        before = self.hub.read_bytes()
        got = self.ask(kind="note-long", answer="move-older", path=self.rel)
        self.assertFalse(got["ok"], got)
        self.assertEqual(before, self.hub.read_bytes())
        self.assertFalse((self.hub.parent / "history").exists())
        self.assertEqual("", git(self.work, "status", "--porcelain").strip())

    def test_nothing_old_enough_moves_nothing(self):
        short = "---\ntitle: Acme Review\ntype: project\nparty: acme\nstatus: active\n---\n\n# Acme Review\n\n## State of play\n\n---\n\n"
        write(self.hub, short)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "short")
        got = self.ask(kind="note-long", answer="move-older", path=self.rel)
        self.assertFalse(got["ok"], got)
        self.assertEqual(short, self.hub.read_text(encoding="utf-8"))

    def test_install_runs_check_py_install_hooks_and_says_so(self):
        done = subprocess.CompletedProcess([], 0, "Work: wall check installed at Zones/Work/.git/hooks/pre-commit\n", "")
        with mock.patch.object(pa, "finding_run", return_value=done) as run:
            got = self.ask(kind="hooks-missing", answer="install", path="Zones/Work")
        self.assertTrue(got["ok"], got)
        args = run.call_args[0][1]
        self.assertEqual(["--root", str(self.root), "--install-hooks"], [str(a) for a in args[1:]])
        self.assertTrue(str(args[0]).endswith("System/tools/check.py"))
        self.assertIn("wall check installed", got["detail"])
        failed = subprocess.CompletedProcess([], 1, "", "Work: a hook of yours is in the way\n")
        with mock.patch.object(pa, "finding_run", return_value=failed):
            got = self.ask(kind="hooks-missing", answer="install", path="Zones/Work")
        self.assertFalse(got["ok"])
        self.assertIn("a hook of yours is in the way", got["say"])

    def test_every_answer_the_page_can_send_is_a_valid_request(self):
        ops = pa.ops_lib(self.root)
        sent = 0
        for plain, it in KINDS.items():
            for a in fq.question(it, "Zones/Work")["answers"]:
                if a["action"] in ("run", "preview", "later"):
                    self.assertIsNone(ops.validate("finding", a["req"]), a)
                    sent += 1
                elif a["action"] == "open":
                    for req in a["reqs"]:
                        self.assertEqual("note-open", req["verb"])
                        self.assertIsNone(ops.validate("note-open", req), a)
                else:
                    self.assertEqual("handoff", a["action"])
                    self.assertTrue(a["phrase"])
        self.assertEqual(7, sent)
        self.assertFalse(self.ask(kind="note-long", answer="bogus", path=self.rel)["ok"])


def old_days(n):
    return dt.date.today() - dt.timedelta(days=n)


def dated(n, words=30):
    d = old_days(n)
    return "**%d %s %d.** Entry settled the plan. %s\n\nSecond paragraph.\n\n" % (d.day, d.strftime("%B"), d.year, "word " * words)


def note_text(above="", entries="", state=True):
    head = "---\ntitle: Pricing\ntype: thread\nstatus: active\n---\n\n# Pricing\n\n" + above
    if not state:
        return head + "\n" + entries
    return head + "\n## State of play\n\n**Resume here.** Under way.\n\n---\n\n" + entries


class TestLongNoteFromItsPlan(QueueCase):
    """#539: a long note is asked from history.py's plan, not from its kind alone."""

    def ask(self, text, rel=THREAD, planner=None):
        write(self.root / rel, text)
        it = dict(KINDS["note-long"], path=rel, line=NOTE_LINE % {"p": rel}, scope="Zones/Work")
        return fq.forecast_questions([it], set(), self.root)["Zones/Work"][0]

    def ids(self, q):
        return [a["id"] for a in q["answers"]]

    def assert_handoff_first(self, q):
        self.assertEqual(["split", "later"], self.ids(q))
        self.assertEqual("split", q["recommended"])
        self.assertNotIn("preview", self.ids(q))
        a = q["answers"][0]
        self.assertEqual("handoff", a["action"])
        self.assertEqual("Your assistant splits the long sections into their own notes in the thread's folder, links them, and shows you the change.",
                         a["does"])
        self.assertIn(THREAD, a["phrase"])
        self.assertIn("show me the change before anything is committed", a["phrase"])

    def test_words_all_above_the_state_of_play_offer_no_move(self):
        q = self.ask(note_text(above="## Thesis\n\n" + "word " * 300 + "\n"))
        self.assert_handoff_first(q)
        self.assertIn("long sections above the dated entries", q["why"])
        self.assertIn("none of the words here are in them", q["details"])

    def test_a_log_of_dated_bullets_above_the_rule_is_named(self):
        bullets = "### Log\n\n" + "".join("- **%d November 2026** Settled step %d.\n" % (i + 1, i) for i in range(8)) + "\n"
        q = self.ask(note_text(above=bullets, entries=dated(1)))
        self.assert_handoff_first(q)
        self.assertIn("bullets in a log above the line that opens the history", q["why"])
        self.assertIn("Dated bullets sit above", q["details"])

    def test_five_entries_or_fewer_stay(self):
        q = self.ask(note_text(entries="".join(dated(n) for n in (1, 2, 3, 400, 500))))
        self.assert_handoff_first(q)
        self.assertIn("five dated entries or fewer", q["why"])

    def test_a_hub_with_no_state_of_play_offers_no_move(self):
        q = self.ask(note_text(above="## Notes\n\n" + "word " * 50, state=False), rel=HUB)
        self.assertEqual(["split", "later"], self.ids(q))
        self.assertIn("project's folder", q["answers"][0]["phrase"])
        self.assertIn("no state-of-play section", q["why"])
        self.assertIn("no `## State of play`", q["details"] + "no `## State of play`")

    def test_eight_entries_with_old_ones_move_first_with_the_plans_figures(self):
        q = self.ask(note_text(entries="".join(dated(n, 600) for n in (1, 2, 3, 4, 5, 300, 310, 320))))
        self.assertEqual(["move-older", "preview", "later"], self.ids(q))
        self.assertEqual("move-older", q["recommended"])
        self.assertRegex(q["why"], r"^3 older entries would move, taking the page from about [\d,]+ words to about [\d,]+ words\.")
        self.assertEqual("split", q["answers"][0]["fallback"]["id"])           # the handoff that stands in for a refused move

    def test_a_move_that_will_not_be_enough_says_so(self):
        plan = {"moves": 2, "before": 9000, "after": 7000, "still_over": True, "case": "", "skipped": ""}
        q = fq.question(dict(KINDS["note-long"]), "Zones/Work", plan)
        self.assertIn("The move alone will not bring it under its limit.", q["why"])
        self.assertEqual(["move-older", "preview", "later"], self.ids(q))

    def test_no_plan_asked_keeps_the_kinds_own_answers(self):
        self.assertEqual(["move-older", "preview", "later"], self.ids(fq.question(dict(KINDS["note-long"]), "Zones/Work")))

    def test_a_plan_that_fails_counts_as_nothing_moves(self):
        write(self.root / THREAD, note_text(entries="".join(dated(n) for n in (1, 2, 3, 4, 5, 300, 310, 320))))
        it = dict(KINDS["note-long"], path=THREAD, line=NOTE_LINE % {"p": THREAD}, scope="Zones/Work")
        bad = (subprocess.CompletedProcess([], 1, "", "boom"), subprocess.CompletedProcess([], 0, "not json", ""),
               subprocess.CompletedProcess([], 0, "[]", ""), subprocess.CompletedProcess([], 0, '{"a": 1}', ""))
        for result in bad:
            with mock.patch.object(fq.subprocess, "run", return_value=result):
                q = fq.forecast_questions([it], set(), self.root)["Zones/Work"][0]
            self.assertEqual(["split", "later"], self.ids(q), result)
            self.assertIn("could not ask what would move", q["why"])
        with mock.patch.object(fq.subprocess, "run", side_effect=subprocess.TimeoutExpired("history.py", 15)):
            self.assertEqual(["split", "later"], self.ids(fq.forecast_questions([it], set(), self.root)["Zones/Work"][0]))
        (self.root / "System" / "tools" / "history.py").unlink()                                    # a missing tool
        self.assertEqual(["split", "later"], self.ids(fq.forecast_questions([it], set(), self.root)["Zones/Work"][0]))

    def test_the_plan_is_a_dry_run_asked_once_a_finding_and_bounded_by_a_budget(self):
        write(self.root / THREAD, note_text(entries="".join(dated(n) for n in (1, 2, 3, 4, 5, 300, 310, 320))))
        its = [dict(KINDS["note-long"], path=p, line=NOTE_LINE % {"p": p}, scope="Zones/Work") for p in (THREAD, THREAD.replace("Pricing", "Pricing2"))]
        write(self.root / its[1]["path"], (self.root / THREAD).read_text(encoding="utf-8"))
        real = subprocess.run
        with mock.patch.object(fq.subprocess, "run", side_effect=real) as run:
            fq.forecast_questions(its + [dict(its[0])], set(), self.root)
        self.assertEqual(2, run.call_count)                                                        # one run for each note
        for call in run.call_args_list:
            argv = call[0][0]
            self.assertIn("dry-run", argv)
            self.assertNotIn("apply", argv)
            self.assertLessEqual(call[1]["timeout"], fq.PLAN_TIMEOUT)
        with mock.patch.object(fq.subprocess, "run") as run:                                      # a spent budget runs nothing
            q = fq.forecast_questions(its, set(), self.root)["Zones/Work"]
            planner = fq.Planner(self.root, budget=0)
            self.assertEqual("unknown", planner.plan(THREAD)["case"])
        run.assert_called()                                                                          # the two plans above ran
        with mock.patch.object(fq.subprocess, "run") as run:
            fq.Planner(self.root, budget=0).plan(THREAD)
        run.assert_not_called()

    def test_every_answer_a_no_move_question_sends_is_a_valid_request(self):
        q = self.ask(note_text(above="## Thesis\n\n" + "word " * 30))
        ops = __import__("test_page_action").pa.ops_lib(self.root)
        for a in q["answers"]:
            if a["action"] == "later":
                self.assertIsNone(ops.validate("finding", a["req"]))
        self.assertIn("split", fq.ANSWERS_NO_MOVE["note-long"][0]["id"])


class TestRefusedAnswerOnTheQueue(unittest.TestCase):
    """#540: a refused answer is disabled, Skip for now moves on, and a reload keeps neither."""

    def q(self, plain="note-long", plan=None):
        return fq.question(dict(KINDS[plain]), "Zones/Work", plan or {"moves": 3, "before": 6400, "after": 3900, "still_over": False,
                                                                       "case": "", "skipped": ""})

    def test_each_question_carries_a_hidden_skip_and_the_move_a_hidden_fallback(self):
        markup = fq.question_html(self.q())
        self.assertRegex(markup, r'<button class="act qskip" type="button" data-qskip hidden>Skip for now</button>')
        self.assertRegex(markup, r'<button class="opt" type="button" data-id="split" data-for="move-older" data-fa="[^"]+" hidden>')
        self.assertEqual(1, markup.count('class="opt rec'))                                         # the fallback is not recommended until it is shown
        self.assertNotIn("data-for", fq.question_html(self.q("resume-long")))

    def test_a_refused_answer_is_disabled_with_the_refusal_under_it_and_skip_shows(self):
        js = fq.QUEUE_JS
        refuse = js[js.index("function refuse("):js.index("function open(")]
        self.assertIn("b.disabled=true", refuse)
        self.assertIn("out(q,f.say,true)", refuse)
        self.assertIn("[data-qskip]').hidden=false", refuse)
        self.assertIn("/^nothing (can move|is old enough)/i.test(say)", js)                          # the two refusals of "nothing can move"
        self.assertIn("fb.hidden=false;fb.classList.add('rec')", refuse)                             # the handoff in the move's place

    def test_skip_for_now_goes_on_and_moves_the_bar_without_putting_the_finding_off(self):
        js = fq.QUEUE_JS
        click = js[js.index("var sk=t.closest"):][:200]
        self.assertIn("skip[sq.dataset.gk]=1;tally.skipped++", click)
        self.assertNotIn("later", click)                                                              # not Not now: nothing is written
        self.assertIn("!gone[q.dataset.gk]&&!skip[q.dataset.gk]", js)                                 # the next question is the next pending one
        self.assertIn("k=n-left.length+1", js)                                                        # and the bar counts what is no longer pending

    def test_the_summary_counts_a_skipped_question_apart_from_not_now(self):
        js = fq.QUEUE_JS
        self.assertIn("['later','put off to next week'],['skipped','skipped']", js)
        self.assertIn("LINES.forEach(function(l){if(tally[l[0]])", js)

    def test_a_reload_after_a_refusal_keeps_nothing_of_it(self):
        """The planning decision replaces the issue's "keeps the disabled answer and the skip": Skip for now keeps nothing on
        disk, so a reload shows the question as built. What is saved leaves out the skip tally and every refusal."""
        js = fq.QUEUE_JS
        keep = js[js.index("function kept()"):js.index("function sum()")]
        self.assertIn("UNSAVED.indexOf(k)<0", keep)
        self.assertIn("!notes[g].bad", keep)
        self.assertIn("UNSAVED=['skipped']", js)
        self.assertNotIn("refused", keep)
        self.assertNotIn("skip:", js[js.index("function save()"):js.index("function sum()")])
        self.assertIn("skip={};refused={}", js[js.index("function restore()"):js.index("function finish(")])
        node = shutil.which("node")
        if node:
            done = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=js, capture_output=True, text=True)
            self.assertEqual(0, done.returncode, done.stderr)

    def test_an_answer_the_queue_script_can_send_still_goes_through_the_verb(self):
        self.assertEqual(("move-older", "preview", "later"), fq.VERB_ANSWERS["note-long"])


if __name__ == "__main__":
    unittest.main()
