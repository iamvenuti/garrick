"""The connector filter (#614): each result of a mail or calendar tool is checked by decide() before the
assistant sees it, warn-only first.

    cd tests && python3 -m unittest test_connector_guard
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from read_guard_case import REPO, SENTENCE, GuardCase  # noqa: E402

TOOL = "mcp__fakemail__search"
OTHER = "mcp__fakedrive__list"


def thread(ident, sender, subject="Hello", to="jo@home.example"):
    return {"id": ident, "from": sender, "to": [to], "subject": subject, "snippet": "A line from the message"}


THREADS = [thread("t1", "Dana <dana@acme.example>", "Pallet floor"), thread("t2", "Theo <theo@birch.example>", "Birch pricing"),
           thread("t3", "Pat <pat@cedar.example>", "Garden"), thread("t4", "x@stranger.example", "Who"),
           thread("t5", "a@maple.example", "Two hats"), thread("t6", "jo@home.example", "Note to self", to="jo@home.example"),
           thread("t7", "friend@gmail.com", "Hi")]


def response(data, as_text=True):
    return [{"type": "text", "text": json.dumps(data) if as_text else data}]


class FilterCase(GuardCase):
    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "enforce", "connector-tools": ["mcp__fakemail__*"]})

    def after(self, tool_response, tool=TOOL, home=None, headless=False, **more):
        home = self.acme if home is None else home
        event = dict({"session_id": "c1", "hook_event_name": "PostToolUse", "tool_name": tool, "cwd": str(home),
                      "tool_input": {}, "tool_response": tool_response}, **more)
        return self.run_hook(event, project_dir=home, headless=headless)

    def replaced(self, reply):
        self.assertIsNotNone(reply)
        out = reply["hookSpecificOutput"]
        self.assertEqual("PostToolUse", out["hookEventName"])
        return out["updatedMCPToolOutput"]

    def kept(self, blocks):
        self.assertEqual(SENTENCE, blocks[-1]["text"])
        self.assertEqual("text", blocks[-1]["type"])
        data = json.loads(blocks[0]["text"])
        return data, [t["id"] for t in data["threads"]]


class Enforced(FilterCase):
    def test_a_project_session_gets_its_own_zones_results_and_the_wall_sentence_with_no_count(self):
        blocks = self.replaced(self.after(response({"threads": THREADS, "resultSizeEstimate": 7, "nextPageToken": "p2"})))
        data, ids = self.kept(blocks)
        self.assertEqual(["t1", "t3"], ids)                       # Acme's own, and Cedar's, an open zone's
        self.assertNotIn("resultSizeEstimate", data)              # no count that gives the total away
        self.assertEqual("p2", data["nextPageToken"])
        self.assertEqual(2, len(blocks))
        everything = json.dumps(blocks)
        for word in ("birch", "Birch", "stranger", "maple", "gmail", "Two hats"):
            self.assertNotIn(word, everything)
        self.assertEqual(1, everything.count(SENTENCE))

    def test_the_other_zone_gets_its_own_results(self):
        blocks = self.replaced(self.after(response({"threads": THREADS}), home=self.birch))
        self.assertEqual(["t2", "t3"], self.kept(blocks)[1])

    def test_a_session_in_an_open_zone_gets_only_open_results(self):
        blocks = self.replaced(self.after(response({"threads": THREADS}), home=self.cedar))
        self.assertEqual(["t3"], self.kept(blocks)[1])

    def test_a_party_with_two_hats_belongs_to_both_zones_so_neither_side_gets_it(self):
        for home in (self.acme, self.birch):
            self.assertNotIn("t5", self.kept(self.replaced(self.after(response({"threads": THREADS}), home=home)))[1])

    def test_your_own_addresses_and_personal_webmail_decide_nothing(self):
        # t6 is from you, t7 from webmail: no party, no label, no read
        for home in (self.acme, self.birch, self.cedar):
            ids = self.kept(self.replaced(self.after(response({"threads": THREADS}), home=home)))[1]
            self.assertNotIn("t6", ids)
            self.assertNotIn("t7", ids)

    def test_a_session_at_the_root_or_in_system_gets_every_result(self):
        for home in (self.root, self.root / "System"):
            self.assertIsNone(self.after(response({"threads": THREADS}), home=home))

    def test_a_result_that_is_all_of_one_party_arrives_whole_with_no_sentence(self):
        only = {"threads": [THREADS[0], thread("t8", "Dana <dana@acme.example>", "Again")]}
        self.assertIsNone(self.after(response(only)))

    def test_a_list_at_the_top_and_an_event_with_attendees(self):
        events = [{"id": "e1", "summary": "Kickoff", "attendees": [{"email": "dana@acme.example"}, {"email": "jo@home.example"}]},
                  {"id": "e2", "summary": "Review", "organizer": {"email": "theo@birch.example"}, "attendees": [{"email": "jo@home.example"}]}]
        blocks = self.replaced(self.after(response(events)))
        self.assertEqual(SENTENCE, blocks[-1]["text"])
        self.assertEqual(["e1"], [e["id"] for e in json.loads(blocks[0]["text"])])

    def test_every_result_refused_leaves_an_empty_list_and_the_sentence(self):
        blocks = self.replaced(self.after(response({"threads": [THREADS[1], THREADS[3]]})))
        self.assertEqual([], self.kept(blocks)[0]["threads"])

    def test_one_message_of_another_zone_is_replaced_by_the_sentence_alone(self):
        message = {"id": "m1", "from": "theo@birch.example", "body": "Price list"}
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(response(message))))
        own = {"id": "m2", "from": "dana@acme.example", "body": "Fine"}
        self.assertIsNone(self.after(response(own)))

    def test_a_result_that_cannot_be_read_as_results_is_replaced_by_the_sentence_alone(self):
        for text in ("Found 3 messages. Subject: Birch pricing", "[1, 2, 3]", '"just a string"', "null"):
            with self.subTest(text=text):
                self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(response(text, as_text=False))))

    def test_a_text_that_is_not_text_passes_and_the_rest_is_still_checked(self):
        image = {"type": "image", "data": "AAAA", "mimeType": "image/png"}
        blocks = self.replaced(self.after([image] + response({"threads": THREADS[:2]})))
        self.assertEqual(image, blocks[0])
        self.assertEqual(SENTENCE, blocks[-1]["text"])

    def test_other_shapes_of_a_response_are_read_the_same_way(self):
        data = {"threads": THREADS[:2]}
        for shape in (json.dumps(data), {"content": response(data)}, data):
            with self.subTest(shape=type(shape).__name__):
                blocks = self.replaced(self.after(shape))
                self.assertEqual(["t1"], self.kept(blocks)[1])

    def test_an_error_passes_unless_it_holds_addresses_that_label_it(self):
        self.assertIsNone(self.after(response("Error 429: quota exceeded", as_text=False), is_error=True))
        self.assertIsNone(self.after("Error 429: quota exceeded", is_error=True))
        blocks = self.replaced(self.after(response("No access to the mailbox of theo@birch.example", as_text=False), is_error=True))
        self.assertEqual([{"type": "text", "text": SENTENCE}], blocks)
        self.assertIsNone(self.after(response("No access to the mailbox of dana@acme.example", as_text=False), is_error=True))

    def test_a_tool_on_no_list_is_not_filtered(self):
        self.assertIsNone(self.after(response({"threads": THREADS}), tool=OTHER))

    def test_the_default_list_is_gmail_and_calendar(self):
        self.settings(**{"read-guard": "enforce"})
        for tool in ("mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Google_Calendar__list_events"):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self.after(response({"threads": THREADS}), tool=tool))
        self.assertIsNone(self.after(response({"threads": THREADS}), tool=TOOL))

    def test_a_scheduled_job_is_logged_and_never_filtered(self):
        self.assertIsNone(self.after(response({"threads": THREADS}), headless=True))
        self.assertIn("deny", {l["decision"] for l in self.log_lines()})

    def test_a_response_of_no_known_shape_is_replaced_by_the_sentence_alone(self):
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(5)))


class WarnOnly(FilterCase):
    def setUp(self):
        super().setUp()
        self.settings(**{"connector-tools": ["mcp__fakemail__*"]})

    def test_nothing_is_removed_and_each_would_be_removal_is_logged(self):
        self.assertIsNone(self.after(response({"threads": THREADS, "resultSizeEstimate": 7})))
        denied = [l for l in self.log_lines() if l["decision"] == "deny"]
        self.assertEqual(5, len(denied))                         # t2, t4, t5, t6, t7
        self.assertEqual({TOOL}, {l["tool"] for l in denied})
        self.assertEqual({"Work"}, {l["zone"] for l in denied})

    def test_the_log_names_no_sender_subject_date_party_or_count(self):
        self.after(response({"threads": THREADS, "resultSizeEstimate": 7}))
        self.assertTrue(self.log_text())
        text = "\n".join(json.dumps({k: v for k, v in line.items() if k != "t"}) for line in self.log_lines())   # the time stamp holds a year
        for word in ("birch", "Birch", "acme", "Acme", "stranger", "gmail", "Pallet", "Hello", "pricing", "2026", "stimate"):
            self.assertNotIn(word, text, word)
        for line in self.log_lines():
            self.assertEqual({"t", "tool", "decision", "zone", "id"}, set(line) - {"kind"})
            self.assertRegex(line["id"], r"^[0-9a-f]{12}$")

    def test_an_unreadable_result_is_passed_and_logged(self):
        self.assertIsNone(self.after(response("Found 3 messages", as_text=False)))
        self.assertEqual("unparsed", self.log_lines()[-1]["kind"])


class ToolsSeen(FilterCase):
    """A connector tool the session used that is on no list is named by check.py, not filtered silently."""

    def test_the_names_of_tools_used_are_noted_and_nothing_else(self):
        self.after(response({"threads": THREADS}))
        self.after(response("anything", as_text=False), tool=OTHER)
        self.after(response("x", as_text=False), tool="Read")       # not a connector tool: not noted
        seen = json.loads((self.state / "tools-seen.json").read_text())
        self.assertEqual({OTHER, TOOL}, set(seen))
        self.assertNotIn("birch", (self.state / "tools-seen.json").read_text())

    def test_the_root_sessions_tools_are_noted_too(self):
        self.after(response("x", as_text=False), tool=OTHER, home=self.root)
        self.assertIn(OTHER, json.loads((self.state / "tools-seen.json").read_text()))

    def findings(self):
        spec = importlib.util.spec_from_file_location("garrick_check_connectors_test", str(REPO / "template/System/tools/check.py"))
        check = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = check
        spec.loader.exec_module(check)
        ws = mock.Mock(root=self.root)
        with mock.patch.dict(os.environ, {"GARRICK_JOBS_DIR": str(self.state.parent / "jobs")}):
            return check.check_connector_tools(ws)

    def test_check_warns_about_a_tool_on_no_list(self):
        self.after(response({"threads": THREADS}))
        self.after(response("x", as_text=False), tool=OTHER)
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertEqual("warning", found[0].severity)
        self.assertIn(OTHER, found[0].message)
        self.assertNotIn(TOOL, found[0].message)

    def test_a_pattern_on_either_list_silences_it(self):
        self.after(response("x", as_text=False), tool=OTHER)
        self.settings(**{"connector-tools": ["mcp__fakemail__*"], "connector-tools-skip": ["mcp__fakedrive__*"]})
        self.assertEqual([], self.findings())
        self.settings(**{"connector-tools": ["mcp__fakemail__*", "mcp__fakedrive__list"]})
        self.assertEqual([], self.findings())

    def test_check_says_nothing_where_the_guard_has_seen_no_tool(self):
        self.assertEqual([], self.findings())

    def test_the_check_is_registered_and_can_be_said_aloud(self):
        spec = importlib.util.spec_from_file_location("garrick_check_connectors_reg", str(REPO / "template/System/tools/check.py"))
        check = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = check
        spec.loader.exec_module(check)
        self.assertIs(check.ALL_CHECKS[-1], check.check_connector_tools)
        self.assertIn("connectors", dict(check.CHECKS))
        self.assertIn("connectors", check.EAR_GROUP)


class Docs(unittest.TestCase):
    def test_the_docs_say_which_harness_gets_no_connector_hook(self):
        text = (REPO / "docs" / "enforced.md").read_text(encoding="utf-8")
        self.assertIn("Codex cannot replace a tool's output", text)
        self.assertIn("kept apart by the instructions only", text)


if __name__ == "__main__":
    unittest.main()
