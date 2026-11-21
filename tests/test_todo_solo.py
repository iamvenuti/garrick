"""The Todo tab on a `solo` page is the Todo tab of 0.72.0 (#612 left this for 0.74.0).

    cd tests && python3 -m unittest test_todo_solo

0.73.0 added the held-request question (.tq*), the "waits for the server" note and the outbox script to the Todo tab. A page with no
machine.json is `solo` and carries none of their markup; a `server` or `roaming` page keeps them. Built in a temporary folder with
HOME in it, never reading this Mac.
"""
import datetime as dt
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import build_workspace, write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "extras" / "status"))
spec = importlib.util.spec_from_file_location("garrick_status_todo_solo", REPO / "extras" / "status" / "status.py")
status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(status)


class Stub:
    def __init__(self, held=(), waits=None):
        self.held, self.waits = list(held), waits or {}

    def role(self, ws):
        return "server" if self.held else "roaming"

    def machine_name(self, ws):
        return "Cedar"

    def held_requests(self, ws, zone):
        return self.held if zone == "Work" else []

    def pending_marks(self, ws, zone):
        return self.waits if zone == "Work" else {}


class SoloTodo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        write(self.root / "Zones" / "Work" / "Todo.md", "# Work\n\n## Inbox\n\n- [ ] Book the room [due:: 2026-11-12]\n")
        self.jobs = Path(self._tmp.name) / "jobs"
        self.jobs.mkdir()

    def page(self, box=None):
        with mock.patch.object(status, "launch_agents", lambda: Path(self._tmp.name) / "LA"), \
                mock.patch.dict(os.environ, {"HOME": str(Path(self._tmp.name) / "home")}), \
                mock.patch.object(status, "outbox_mod", lambda: box):
            return status.build(self.root, now=dt.datetime(2026, 11, 10, 10, 0), folder=self.jobs)

    def todo(self, page):
        start = page.index('id="tab-todo"')
        return page[start:page.index("</section>", start)]

    def test_a_solo_page_has_none_of_the_machine_states_in_its_todo_tab(self):
        tab = self.todo(self.page(None))
        self.assertIn("Book the room", tab)
        for gone in ('class="tq"', 'class="tqi"', "waits for the server", "data-outbox"):
            self.assertNotIn(gone, tab)

    def test_the_tab_is_the_same_with_the_outbox_present_but_solo(self):
        class Solo(Stub):
            def role(self, ws):
                return "solo"
        self.assertEqual(self.todo(self.page(None)), self.todo(self.page(Solo())))

    def test_a_server_page_keeps_the_held_question(self):
        held = [{"zone": "Work", "id": "a1", "machine": "Birch laptop", "verb": "todo-done", "line": "- [ ] Book the room", "text": "Book the room",
                 "now": ["- [ ] Book the room 2"]}]
        tab = self.todo(self.page(Stub(held=held)))
        self.assertIn('class="tqi"', tab)
        self.assertIn('data-outbox="drop"', tab)

    def test_the_held_question_css_is_only_what_a_held_question_uses(self):
        used = {"tq", "tqi", "tqt", "tqa", "tqmore", "tql"}
        for name in used:
            self.assertIn("." + name, status.TODO_CSS)
        self.assertNotIn('class="tq', self.todo(self.page(None)))


if __name__ == "__main__":
    unittest.main()
