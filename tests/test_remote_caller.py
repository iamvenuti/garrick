"""The remote caller (#701): `remote` has no right a session lacks, and perform() always knows who asks.

    cd tests && python3 -m unittest test_remote_caller

A remote assistant is the first caller that is not on the Mac. Its rights are never above a session's: every page-only
verb, the party dialog's verb, the verbs the engine keeps from a Telegram session and every verb whose scope is the
machine are refused to it. Nothing has to prove the rest, because it carries no right of its own.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_page_action as base  # noqa: E402

pa = base.pa
REPO = base.REPO


class RemoteCase(base.ActionCase):
    def go(self, req, via="remote"):
        return pa.perform(self.root, req, pa.ops_lib(self.root), via=via)

    def refused(self, req):
        out, _, why = self.go(req)
        self.assertFalse(out["ok"], (req, out))
        self.assertEqual(pa.REMOTE_REFUSED, out["say"], req)
        return out


class TestTheCallerIsNamed(unittest.TestCase):
    def test_remote_is_a_caller_in_both_copies(self):
        ops = pa.ops_lib(Path(base.__file__).resolve().parent.parent / "template")
        self.assertIn("remote", pa.CALLERS)
        self.assertEqual(tuple(pa.CALLERS), tuple(ops.CALLERS))

    def test_perform_has_no_default_for_via(self):
        import inspect
        self.assertIs(pa._NO_CALLER, inspect.signature(pa.perform).parameters["via"].default)

    def test_a_call_without_via_raises(self):
        with self.assertRaises(TypeError):
            pa.perform(Path("."), {"verb": "todo-add"})
        with self.assertRaises(TypeError):
            pa.perform(Path("."), {"verb": "todo-add"}, None)

    def test_every_call_of_perform_in_the_repository_names_its_caller(self):
        """A call that leaves `via` out would get no rights at all today; a test of the source keeps a later one honest."""
        roots = [REPO / "extras", REPO / "template", REPO / "tests"]
        offenders = []
        for root in roots:
            for path in root.rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    fn = node.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
                    if name != "perform":
                        continue
                    if any(k.arg == "via" for k in node.keywords) or len(node.args) >= 4 or any(isinstance(a, ast.Starred) for a in node.args):
                        continue
                    if any(k.arg is None for k in node.keywords):
                        continue
                    # a method called perform that is not page_action's (an executor stand-in) takes other arguments
                    if path.name == "test_remote_caller.py":      # this file calls it bare on purpose
                        continue
                    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "self":
                        continue
                    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "model":
                        continue
                    offenders.append("%s:%d" % (path.relative_to(REPO), node.lineno))
        self.assertEqual([], offenders)


class TestWhatRemoteIsRefused(RemoteCase):
    def test_every_page_only_verb(self):
        for verb in pa.PAGE_ONLY:
            with self.subTest(verb=verb):
                self.refused({"verb": verb})

    def test_the_party_verb_and_the_page_only_answers(self):
        self.refused({"verb": "new-project-party", "zone": "Work", "name": "Cedar", "new_party": "Cedar Ltd"})
        for answer in pa.PAGE_ONLY_ANSWERS:
            with self.subTest(answer=answer):
                self.refused({"verb": "finding", "kind": "note-long", "path": "x.md", "answer": "%s-0a1b2c" % answer})

    def test_the_verbs_the_engine_keeps_from_a_telegram_session(self):
        for verb in pa.KEPT_FROM_TELEGRAM:
            with self.subTest(verb=verb):
                self.refused({"verb": verb, "zone": "Work"})

    def test_the_engine_names_each_of_them(self):
        """The list is the one engine.py's comment gives above INTAKE; a verb dropped there or here fails."""
        text = (REPO / "extras" / "status" / "engine.py").read_text(encoding="utf-8")
        comment = text.split("# The commands an Act session may run", 1)[1].split("INTAKE =", 1)[0]
        comment = " ".join(comment.replace("#", " ").split())
        for verb in ("rename", "move", "delete", "undo", "settings", "run"):
            self.assertIn(verb, pa.KEPT_FROM_TELEGRAM)
            self.assertRegex(comment, r"\b%s\b" % verb)

    def test_every_verb_that_works_on_the_machine(self):
        ops = pa.ops_lib(self.root)
        for verb, spec in ops.DECLARED.items():
            if spec.scope == "machine":
                with self.subTest(verb=verb):
                    self.refused({"verb": verb})

    def test_an_undeclared_verb_and_a_request_that_is_not_one(self):
        for req in ({"verb": "no-such-verb"}, {"verb": 7}, {}, [], "todo-add", None):
            with self.subTest(req=req):
                out, _, _ = self.go(req)
                self.assertFalse(out["ok"], req)

    def test_a_session_keeps_what_it_had(self):
        out, _, _ = self.go({"verb": "todo-add", "zone": "Work", "text": "Book the room"}, via="session")
        self.assertTrue(out["ok"], out)

    def test_remote_gets_no_right_over_a_session(self):
        """For every declared verb: refused to a session means refused to remote."""
        ops = pa.ops_lib(self.root)
        for verb in ops.DECLARED:
            session, _, _ = self.go({"verb": verb}, via="session")
            remote, _, _ = self.go({"verb": verb}, via="remote")
            if not session["ok"] and session["say"] == pa.PAGE_REFUSED:
                self.assertFalse(remote["ok"], verb)
                self.assertEqual(pa.REMOTE_REFUSED, remote["say"], verb)

    def test_an_unknown_caller_has_no_page_right(self):
        out, _, _ = self.go({"verb": "walls-allow"}, via="telegram")
        self.assertEqual(pa.PAGE_REFUSED, out["say"])

    def test_the_ones_a_remote_assistant_may_send_still_work(self):
        out, _, _ = self.go({"verb": "todo-add", "zone": "Work", "text": "Book the room"})
        self.assertTrue(out["ok"], out)
        self.assertIn("Book the room", (self.work / "Todo.md").read_text(encoding="utf-8"))

    def test_the_record_names_remote(self):
        out, _, _ = self.go({"verb": "todo-add", "zone": "Work", "text": "Call the carrier", "op": "aaaa0000bbbb1111"})
        self.assertTrue(out["ok"], out)
        rows = [json.loads(l) for l in (self.jobs / "operations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertIn("remote", [r.get("via") for r in rows])

    def test_the_command_line_believes_remote_and_still_not_page(self):
        self.assertEqual("remote", pa.caller("remote", self.root))
        self.assertEqual("session", pa.caller("page", self.root))
        self.assertEqual("session", pa.caller("ask", self.root))


if __name__ == "__main__":
    unittest.main()
