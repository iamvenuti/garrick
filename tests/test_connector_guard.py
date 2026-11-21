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


class BrokenIntake(FilterCase):
    """The filter cannot read the Parties table (or the intake script that matches an address): on, it removes every
    result of the tool and says the wall sentence once; watch only, it removes nothing and logs that it could not decide."""

    HEADER_ONLY = "# Context\n\n## Parties\n\n| Party | What it is | Zone | Tag | Domains |\n|---|---|---|---|---|\n"

    def break_it(self, how):
        context = self.root / "System" / "context.md"
        if how == "missing table":
            context.write_text("# Context\n\n## Me\n\nJo Example.\n", encoding="utf-8")
        elif how == "no rows":
            context.write_text(self.HEADER_ONLY, encoding="utf-8")
        elif how == "unreadable":
            context.unlink()
            context.mkdir()                     # a folder where the file should be: reading it fails
        elif how == "no intake script":
            skills = self.root / "System" / "skills"
            skills.unlink()
            (skills / "intake").mkdir(parents=True)
        elif how == "intake does not load":
            skills = self.root / "System" / "skills"
            skills.unlink()
            (skills / "intake").mkdir(parents=True)
            (skills / "intake" / "intake.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
        else:
            raise AssertionError(how)

    HOWS = ("missing table", "no rows", "unreadable", "no intake script", "intake does not load")

    def test_on_every_result_goes_and_the_sentence_stands_alone_once(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                self.setUp()
                self.break_it(how)
                got = self.replaced(self.after(response({"threads": THREADS, "resultSizeEstimate": 7})))
                self.assertEqual([{"type": "text", "text": SENTENCE}], got)

    def test_watch_only_removes_nothing_and_logs_that_it_could_not_decide(self):
        for how in self.HOWS:
            with self.subTest(how=how):
                self.setUp()
                self.settings(**{"connector-tools": ["mcp__fakemail__*"]})
                self.break_it(how)
                self.assertIsNone(self.after(response({"threads": THREADS})))
                [line] = self.log_lines()
                self.assertEqual(("undecided", TOOL), (line["decision"], line["tool"]))
                self.assertEqual({"t", "tool", "decision", "zone", "id", "kind"}, set(line))
                text = self.log_text()
                for word in ("acme", "Acme", "birch", "Pallet", "stranger", "Hello"):
                    self.assertNotIn(word, text.replace(line["t"], ""), word)

    def test_a_scheduled_job_is_logged_and_never_refused(self):
        self.break_it("no rows")
        self.assertIsNone(self.after(response({"threads": THREADS}), headless=True))
        self.assertEqual("undecided", self.log_lines()[-1]["decision"])

    def test_a_session_at_the_root_is_not_filtered_and_a_tool_on_no_list_is_left_alone(self):
        self.break_it("no rows")
        self.assertIsNone(self.after(response({"threads": THREADS}), home=self.root))
        self.assertIsNone(self.after(response({"threads": THREADS}), tool=OTHER))

    def test_the_tools_name_alone_reaches_the_log(self):
        self.break_it("missing table")
        self.after(response({"threads": THREADS}))
        self.assertEqual(["undecided"], [l["decision"] for l in self.log_lines()])


class SettingsAndStateUnreadable(FilterCase):
    """A settings file that is there and cannot be read is On; the guard's own folder never switches the filter off."""

    def test_a_settings_file_that_does_not_parse_is_on(self):
        (self.root / "System" / "garrick-settings.json").write_text("{not json", encoding="utf-8")
        blocks = self.replaced(self.after(response({"threads": THREADS}), tool="mcp__claude_ai_Gmail__search_threads"))
        data, ids = self.kept(blocks)
        self.assertEqual(["t1", "t3"], ids)     # the same filtering On does; the tools list falls back to the default

    def test_a_settings_file_that_cannot_be_read_is_on(self):
        path = self.root / "System" / "garrick-settings.json"
        path.unlink()
        path.mkdir()
        self.assertIsNotNone(self.after(response({"threads": THREADS}), tool="mcp__claude_ai_Gmail__search_threads"))

    def test_no_settings_file_is_what_it_was_watch_only(self):
        (self.root / "System" / "garrick-settings.json").unlink()
        self.assertIsNone(self.after(response({"threads": THREADS}), tool="mcp__claude_ai_Gmail__search_threads"))

    def test_the_guards_own_folder_not_being_writable_still_filters(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text("a file where the folder should be", encoding="utf-8")
        data, ids = self.kept(self.replaced(self.after(response({"threads": THREADS}))))
        self.assertEqual(["t1", "t3"], ids)

    def test_a_result_the_filter_fails_on_is_removed_when_on_and_passes_when_watching(self):
        deep = "[" * 100000 + "]" * 100000          # json.loads raises RecursionError: a fault inside the filter
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(response(deep, as_text=False))))
        self.settings(**{"connector-tools": ["mcp__fakemail__*"]})
        self.assertIsNone(self.after(response(deep, as_text=False)))


class ToolsSeen(FilterCase):
    """A connector tool the session used that is on no list is named by check.py, not filtered silently."""

    def test_the_names_of_tools_used_are_noted_and_nothing_else(self):
        self.after(response({"threads": THREADS}))
        self.after(response("anything", as_text=False), tool=OTHER)
        self.after(response("x", as_text=False), tool="Read")       # not a connector tool: not noted
        seen = json.loads((self.state / "tools-seen.json").read_text())
        self.assertEqual({OTHER, TOOL}, set(seen))
        self.assertNotIn("birch", (self.state / "tools-seen.json").read_text())

    def test_the_record_of_tools_is_replaced_whole_and_leaves_no_temporary_file(self):
        self.after(response({"threads": THREADS}))
        self.after(response("x", as_text=False), tool=OTHER)
        self.assertEqual(["tools-seen.json"], [p.name for p in self.state.iterdir() if p.name.startswith("tools-seen")])
        with mock.patch("os.replace", wraps=os.replace) as replaced:
            import importlib
            sys.path.insert(0, str(REPO / "extras" / "hooks"))
            try:
                guard = importlib.import_module("read_guard")
            finally:
                sys.path.remove(str(REPO / "extras" / "hooks"))
            guard.note_tool(str(self.state), "mcp__fakemail__other")
        self.assertTrue(any(str(c.args[1]).endswith("tools-seen.json") for c in replaced.call_args_list))
        self.assertIn("mcp__fakemail__other", json.loads((self.state / "tools-seen.json").read_text()))

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
        self.assertEqual(1, sum(1 for c in check.ALL_CHECKS if c is check.check_connector_tools))
        self.assertIn(check.check_connector_tools, check.ALL_CHECKS)
        self.assertIn("connectors", dict(check.CHECKS))
        self.assertIn("connectors", check.EAR_GROUP)


class Containers(FilterCase):
    """Fix round: the filter reads every list and every field of a result, and fails closed (W1, S4, C3)."""

    def shown(self, data, **more):
        blocks = self.replaced(self.after(response(data), **more))
        return blocks, "\n".join(b.get("text", "") for b in blocks)

    def test_an_empty_list_is_never_the_results_list(self):
        blocks, text = self.shown({"labels": [], "threads": [THREADS[0], THREADS[1]]})
        data = json.loads(blocks[0]["text"])
        self.assertEqual(["t1"], [t["id"] for t in data["threads"]])
        self.assertEqual([], data["labels"])
        self.assertNotIn("birch", text)

    def test_every_list_of_results_is_filtered(self):
        blocks, text = self.shown({"threads": [THREADS[0]], "messages": [THREADS[1], THREADS[2]]})
        data = json.loads(blocks[0]["text"])
        self.assertEqual(["t1"], [t["id"] for t in data["threads"]])
        self.assertEqual(["t3"], [t["id"] for t in data["messages"]])
        self.assertNotIn("birch", text)

    def test_a_list_nested_in_a_dict_is_filtered(self):
        blocks, text = self.shown({"page": {"threads": [THREADS[0], THREADS[1]]}, "nextPageToken": "p2"})
        data = json.loads(blocks[0]["text"])
        self.assertEqual(["t1"], [t["id"] for t in data["page"]["threads"]])
        self.assertEqual("p2", data["nextPageToken"])
        self.assertNotIn("birch", text)

    def test_a_single_event_is_judged_whole_so_its_title_goes_with_its_attendees(self):
        event = {"summary": "Birch pricing review", "attendees": [{"email": "theo@birch.example"}, {"email": "jo@home.example"}]}
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(response(event))))
        own = {"summary": "Kickoff", "attendees": [{"email": "dana@acme.example"}]}
        self.assertIsNone(self.after(response(own)))

    def test_a_body_beside_a_headers_list_is_judged_with_it(self):
        message = {"headers": [{"name": "From", "value": "theo@birch.example"}], "body": "Price list for the quarter"}
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after(response(message))))

    def test_the_fields_beside_the_results_are_judged_by_their_own_addresses(self):
        blocks, text = self.shown({"threads": [THREADS[0]], "owner": "theo@birch.example", "title": "Birch inbox"})
        data = json.loads(blocks[0]["text"])
        self.assertEqual({"threads"}, set(data))
        self.assertNotIn("Birch", text)

    def test_a_count_of_any_kind_goes_when_anything_is_removed(self):
        data = {"threads": [THREADS[0], THREADS[1]], "total": "9", "hits": 9, "messagesUnread": 3, "threadsUnread": 2,
                "resultSizeEstimate": 9, "remaining": 4, "hasMore": True, "nextPageToken": "p2",
                "meta": {"total": 9, "size": "9"}}
        blocks, text = self.shown(data)
        kept = json.loads(blocks[0]["text"])
        self.assertEqual({"threads", "nextPageToken", "meta"}, set(kept))
        self.assertEqual({}, kept["meta"])
        self.assertEqual(["t1"], [t["id"] for t in kept["threads"]])

    def test_a_count_stays_when_nothing_is_removed(self):
        self.assertIsNone(self.after(response({"threads": [THREADS[0]], "total": 1})))

    def test_a_resource_block_is_judged_like_text(self):
        resource = {"type": "resource", "resource": {"uri": "mail://x", "mimeType": "application/json",
                                                     "text": json.dumps({"threads": THREADS[:2]})}}
        blocks = self.replaced(self.after([resource]))
        self.assertEqual(SENTENCE, blocks[-1]["text"])
        self.assertEqual(["t1"], [t["id"] for t in json.loads(blocks[0]["resource"]["text"])["threads"]])
        blob = {"type": "resource", "resource": {"uri": "mail://y", "blob": "AAAA"}}
        self.assertEqual([{"type": "text", "text": SENTENCE}], self.replaced(self.after([blob])))

    def test_structured_content_is_judged_too(self):
        reply = {"content": response({"threads": [THREADS[0]]}), "structuredContent": {"threads": THREADS[:2]}}
        blocks = self.replaced(self.after(reply))
        self.assertEqual(SENTENCE, blocks[-1]["text"])
        own = {"content": response({"threads": [THREADS[0]]}), "structuredContent": {"threads": [THREADS[0]]}}
        self.assertIsNone(self.after(own))

    def test_an_error_naming_another_zones_party_or_person_is_replaced(self):
        for text in ("Not found: Birch & Co pricing thread", "No thread from birch about prices", "Cannot open Dana Whitlock's calendar"):
            with self.subTest(text=text):
                home = self.birch if "Dana" in text else self.acme
                self.assertEqual([{"type": "text", "text": SENTENCE}],
                                 self.replaced(self.after(response(text, as_text=False), is_error=True, home=home)))
        self.assertIsNone(self.after(response("Not found: Acme Corp pricing thread", as_text=False), is_error=True))
        self.assertIsNone(self.after(response("Error 500: try again later", as_text=False), is_error=True))

    def test_in_warn_only_nothing_changes(self):
        self.settings(**{"connector-tools": ["mcp__fakemail__*"]})
        self.assertIsNone(self.after(response({"labels": [], "threads": THREADS[:2], "total": 2})))
        self.assertTrue([l for l in self.log_lines() if l["decision"] == "deny"])


class Docs(unittest.TestCase):
    def test_the_docs_say_which_harness_gets_no_connector_hook(self):
        text = (REPO / "docs" / "enforced.md").read_text(encoding="utf-8")
        self.assertIn("Codex cannot replace a tool's output", text)
        self.assertIn("kept apart by the instructions only", text)


if __name__ == "__main__":
    unittest.main()
