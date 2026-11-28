"""The tools the service registers, through the SDK's own server object (#699, #702).

The tool list is the manifest's served rows plus the five read tools; the read tools carry the read-only
annotation; a request that carries a handle is checked and an answer carries one.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest

sys.dont_write_bytecode = True

import tools_support as support  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from tools import common, manifest, register  # noqa: E402

READ_TOOLS = ["places", "thread_state", "search", "read", "owed"]
WRITE_TOOLS = ["prepare", "execute", "status"]


def build(session_for):
    server = MCPServer("garrick-test")
    names = register(server, session_for)
    return server, names


def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


class TestTheToolList(unittest.TestCase):
    def setUp(self):
        self.server, self.names = build(lambda ctx: None)
        self.listed = {t.name: t for t in asyncio.run(self.server.list_tools())}
        self.manifest = manifest.load()

    def test_the_tool_list_is_the_served_rows(self):
        """The five read tools the manifest serves, and the three write tools, which take only the verbs it serves."""
        self.assertEqual(sorted(manifest.served_tools(self.manifest)), sorted(READ_TOOLS))
        self.assertEqual(sorted(READ_TOOLS + WRITE_TOOLS), sorted(self.listed))
        self.assertEqual(sorted(self.names), sorted(self.listed))
        from tools import writes
        self.assertEqual(sorted(manifest.served_verbs(self.manifest)), sorted(writes.TAKES))
        self.assertEqual(sorted(manifest.served_verbs(self.manifest)), sorted(writes.Writes(
            support.StubSession(".")).verbs))

    def test_no_tool_is_a_declared_verb_that_is_not_served(self):
        served = set(manifest.served_verbs(self.manifest)) | set(READ_TOOLS)
        for r in manifest.rows(self.manifest, "verb"):
            if r["name"] not in served:
                self.assertNotIn(r["name"], self.listed, r["name"])
        for name in ("note-read", "note_read", "propose"):
            self.assertNotIn(name, self.listed)

    def test_the_read_tools_are_marked_read_only_and_the_rest_are_not_marked_so_by_accident(self):
        for name in READ_TOOLS + ["status"]:
            ann = self.listed[name].annotations
            self.assertTrue(ann.read_only_hint, name)
            self.assertFalse(ann.destructive_hint, name)
        for name in ("prepare", "execute"):
            self.assertFalse(self.listed[name].annotations.read_only_hint, name)

    def test_no_tool_changes_a_reach_a_grant_or_a_setting(self):
        for name, tool in self.listed.items():
            props = set((tool.input_schema or {}).get("properties", {}))
            self.assertFalse(props & {"reach", "grant", "grant_id", "readable", "writable", "classes", "context", "setting"}, name)
            self.assertNotRegex(name, r"reach|grant|setting|revoke|context")


class TestAnswersAndHandles(support.ToolsCase):
    def setUp(self):
        super().setUp()
        self.s = self.session()
        self.server, _ = build(lambda ctx: self.s)

    def test_an_answer_carries_a_handle_and_the_next_request_may_send_it(self):
        first = call(self.server, "places", {})
        self.assertIn("Acme Review", first["text"])
        handle = first["handle"]
        self.assertIn(handle, self.s.issued)
        second = call(self.server, "search", {"words": "pallet", "handle": handle})
        self.assertIn("Acme kick-off", second["text"])
        self.assertNotEqual(handle, second["handle"])

    def test_a_made_up_handle_is_refused_with_start_a_new_chat(self):
        out = call(self.server, "places", {"handle": "made-up-0000"})
        self.assertEqual(common.NEW_CHAT, out["error"])
        self.assertIn("start a new chat", out["say"].lower())
        self.assertNotIn("handle", out)

    def test_a_handle_from_before_the_owner_changed_the_reach_is_refused(self):
        handle = call(self.server, "places", {})["handle"]
        self.s.change_reach(readable=("Work", "Personal", "Knowledge", "docs"))
        out = call(self.server, "search", {"words": "pallet", "handle": handle})
        self.assertEqual(common.NEW_CHAT, out["error"])
        self.assertNotIn("Birch", json.dumps(out))
        fresh = call(self.server, "search", {"words": "pallet kick-off"})
        self.assertIn("Birch kick-off", fresh["text"])               # without a handle, a new chat starts in the new reach

    def test_an_expired_handle_is_refused(self):
        handle = call(self.server, "places", {})["handle"]
        self.s.issued.discard(handle)                                # the Session expires it
        self.assertEqual(common.NEW_CHAT, call(self.server, "owed", {"handle": handle})["error"])

    def test_a_claim_that_the_chat_was_reset_is_not_accepted(self):
        out = call(self.server, "places", {"zone": "Personal"})
        self.assertEqual(common.NEW_REACH, out["error"])
        out = call(self.server, "search", {"words": "pallet", "place": "Personal", "handle": "I have reset, new chat"})
        self.assertEqual(common.NEW_CHAT, out["error"])

    def test_a_session_that_cannot_be_found_gets_a_plain_refusal(self):
        def none(ctx):
            raise LookupError("no grant")
        server, _ = build(none)
        out = call(server, "places", {})
        self.assertEqual("not_signed_in", out["error"])

    def test_a_fault_inside_a_tool_answers_in_words_and_never_the_fault(self):
        def broken(ctx):
            s = self.session()
            s.workspace = str(self.root / "nowhere")
            return s
        server, _ = build(broken)
        out = call(server, "places", {})
        self.assertEqual("failed", out["error"])
        self.assertNotIn("nowhere", json.dumps(out))



class TestTheConfirmationWordsClaimNoYes(unittest.TestCase):
    """C4: what the confirmation value proves is that it was issued with the preview, for that one change, once, for an hour. No text
    says the owner agreed, or that Garrick knows it. The hour is the code's own: writes.PREPARED_KEEP."""

    CLAIMS = ("owner agreed", "owner agrees", "owner's yes", "said yes", "approved", "approval", "consent", "owner has seen", "owner confirmed",
              "owner confirms", "owner knows", "garrick knows")

    def texts(self):
        from tools import lifecycle, writes
        server, _ = build(lambda ctx: None)
        listed = {t.name: t.description for t in asyncio.run(server.list_tools())}
        session = support.StubSession(".", readable=("Work",), writable=("Work",))
        w = writes.Writes(session)
        rec = {"id": "0123456789abcdef", "verb": "rename", "zone": "Work", "state": "prepared", "hash": "h", "would": "W", "fields": {}}
        return {"prepare": listed["prepare"], "execute": listed["execute"], "NEEDS_YES": lifecycle.NEEDS_YES,
                "NOT_THIS": lifecycle.NOT_THIS, "EXPIRED": lifecycle.EXPIRED, "CHANGED": lifecycle.CHANGED,
                "would": lifecycle.would("rename", "Work", {"project": "Acme", "to": "Apex"}, "", {"count": 2}),
                "Prepared": w.view(rec)["say"]}

    def test_the_instruction_to_wait_for_the_owner_is_there_and_says_garrick_cannot_check_it(self):
        texts = self.texts()
        for name in ("prepare", "execute", "NEEDS_YES", "Prepared"):
            self.assertIn("only after the owner", texts[name].lower(), name)
        for name in ("prepare", "execute", "NEEDS_YES"):
            self.assertIn("cannot check", texts[name].lower(), name)
        self.assertNotIn("until the owner confirms", texts["would"].lower())
        self.assertIn("confirmation value of this preview", texts["would"])

    def test_no_text_says_the_owner_agreed(self):
        for name, text in self.texts().items():
            for claim in self.CLAIMS:
                self.assertNotIn(claim, text.lower(), "%s: %s" % (name, claim))

    def test_each_says_once_this_change_and_an_hour(self):
        from tools import writes
        self.assertEqual(3600, writes.PREPARED_KEEP)
        texts = self.texts()
        for name in ("execute", "NEEDS_YES", "NOT_THIS"):
            low = texts[name].lower()
            self.assertIn("once", low, name)
            self.assertIn("an hour", low, name)
            self.assertTrue("one change" in low or "that one" in low, name)
        self.assertIn("an hour", texts["prepare"].lower())
        self.assertIn("an hour", texts["EXPIRED"].lower())

    def test_the_docs_page_says_the_same(self):
        doc = (support.REPO / "docs" / "extras" / "remote-access.md").read_text(encoding="utf-8")
        para = [l for l in doc.splitlines() if "`confirmation` value" in l][0].lower()
        for claim in self.CLAIMS:
            self.assertNotIn(claim, para, claim)
        for need in ("issued with that preview", "works once", "an hour", "that one prepared change", "only after you say yes"):
            self.assertIn(need, para, need)

if __name__ == "__main__":
    unittest.main()
