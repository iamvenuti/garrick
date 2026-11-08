"""The 0.60.0 release fixes of the model branch (#444, #445): a project naming two walled parties is the yes only
for that project, never for every other place; `*knowledge` written in frontmatter; a block-style `party:` list;
a blank Walled cell. Invented names only. The fixture holds a `Both` project naming acme and birch.

    cd tests && python3 -m unittest test_release_fixes
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import write  # noqa: E402
from walls_fixture import build  # noqa: E402
from test_party_flags import Base  # noqa: E402

import garrick_lib as lib  # noqa: E402
import scaffold  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ask_scope = load("garrick_ask_scope_fixes", REPO / "extras" / "status" / "ask_scope.py")
ask_tools = load("garrick_ask_tools_fixes", REPO / "extras" / "status" / "ask_tools.py")
page_action = load("garrick_page_action_fixes", REPO / "extras" / "status" / "page_action.py")


class Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build(self.root)
        self.work = self.root / "Zones" / "Work"
        self.ctx = lib.load_context(self.root)
        self.assertEqual({"acme", "birch"}, set(lib.labels(self.root, self.work / "Both")))


class OneJointProjectIsNotEveryProjectsYes(Fixture):
    def test_any_wall_stops_a_mixed_set_though_a_project_names_both(self):
        self.assertTrue(ask_scope.any_wall(self.ctx, {"acme"}, {"birch"}, lib))
        self.assertFalse(ask_scope.any_wall(self.ctx, {"acme"}, {"acme"}, lib))

    def test_crossing_and_two_walled_stop_with_no_destination(self):
        self.assertTrue(page_action.two_walled(lib, self.ctx, ["acme", "birch"]))
        self.assertFalse(page_action.two_walled(lib, self.ctx, ["acme", "cedar"]))
        self.assertFalse(lib.meets_in(self.ctx, {"acme", "birch"}))

    def test_a_mixed_set_into_a_project_naming_only_one_still_stops(self):
        self.assertFalse(lib.meets_in(self.ctx, {"acme", "birch"}, lib.labels(self.root, self.work / "Northwind")))
        self.assertTrue(lib.meets_in(self.ctx, {"acme", "birch"}, lib.labels(self.root, self.work / "Both")))

    def conversation(self, held):
        c = object.__new__(ask_tools.Conversation)
        c.ws = self.root
        c.held_tags = lambda lib_: set(held)
        return c

    def test_ask_crosses_tests_the_scope_at_hand(self):
        c = self.conversation({"birch"})
        self.assertTrue(c.crosses({"acme"}, lib, self.ctx))                  # Northwind names acme only
        self.assertFalse(c.crosses({"acme", "birch"}, lib, self.ctx))        # a scope naming both
        self.assertTrue(c.crosses({"acme"}, lib, self.ctx, extra={"birch"}))

    def test_ask_zone_parties_and_the_project_list_stop_on_two_walled(self):
        c = self.conversation(set())
        sc = ask_scope
        names = {"Work": {"Northwind": {}, "Harbour": {}, "Both": {}}}
        self.assertIsNone(c.zone_parties("Work", names, self.ctx, sc, lib))
        self.assertFalse(lib.meets_in(self.ctx, {"acme", "birch"}))      # the project list's check
        self.assertEqual({"acme"}, c.zone_parties("Work", {"Work": {"Northwind": {}}}, self.ctx, sc, lib))

    def test_open_section_rows_skip_a_mixed_page_though_a_project_names_both(self):
        self.assertTrue(page_action.two_walled(lib, self.ctx, ["acme", "birch"]))


class FrontmatterSentinel(Fixture):
    def test_knowledge_sentinel_in_frontmatter_is_no_label(self):
        write(self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260401-star.md",
              "---\ntitle: S\ntype: source\nzone: Work\nparties: [\"*knowledge\"]\n---\n\n# S\n")
        got = lib.labels(self.root, self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260401-star.md", self.ctx)
        self.assertIsNone(got)
        self.assertEqual("deny", lib.decide({"cedar"}, got, "read", self.ctx))
        self.assertEqual("deny", lib.decide({"cedar"}, got, "write", self.ctx))
        hub = self.work / "Star" / "Star.md"
        write(hub, "---\ntitle: Star\ntype: project\nzone: Work\nparty: \"*knowledge\"\nstatus: active\n---\n\n# Star\n")
        write(hub.parent / "x.md", "# x\n")
        self.assertIsNone(lib.labels(self.root, hub.parent / "x.md", self.ctx))


class ScaffoldFixes(Base):

    def test_a_block_list_is_replaced_whole(self):
        note = self.work / "Joint" / "Joint.md"
        write(note, "---\ntitle: Joint\ntype: project\nzone: Work\nparty:\n  - cedar\n  - acme\nstatus: active\n---\n\n# Joint\n")
        scaffold.write_party_line(note, ["cedar", "acme", "birch"])
        text = note.read_text()
        self.assertIn("party: [cedar, acme, birch]\nstatus: active\n", text)
        self.assertNotIn("  - ", text)
        self.assertEqual(["cedar", "acme", "birch"], lib.tag_list(lib.parse_frontmatter(note)["party"]))
        self.assertTrue(text.endswith("---\n\n# Joint\n"))

    def test_a_blank_walled_cell_can_be_set_to_walled(self):
        path = self.root / "System" / "context.md"
        text = path.read_text()
        self.assertIn("| `lumen` | yes |", text)
        path.write_text(text.replace("| `lumen` | yes |", "| `lumen` |  |"))
        self.assertTrue(lib.is_walled(lib.load_context(self.root), "lumen"))
        code, said, _ = self.run_scaffold("party", "--tag", "lumen", "--walled")
        self.assertNotIn("already", said)
        self.assertIn("| `lumen` | yes |", path.read_text())

    def test_the_example_config_has_no_walls_key(self):
        self.assertNotIn('"walls"', (REPO / "examples" / "example-work" / "config.json").read_text())


if __name__ == "__main__":
    unittest.main()
