"""The walls migration and the owner's own name (#458): a party named after the owner is proposed renamed, and the
report lists the files a name would refuse once the flags are written, before the yes."""

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import test_update  # noqa: E402  (its Case builds a real install; imported as a module so its tests are not collected twice)
from fixtures import write  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class TestOwnerNamedParty(test_update.Case):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(REPO / "tests"))
        import legacy_walls
        legacy_walls.build(self.root)
        self.context = self.root / "System" / "context.md"
        text = self.context.read_text(encoding="utf-8")
        # the owner's own party carries the owner's name, as a real workspace's does
        self.context.write_text(text.replace("| Jo Example | Own affairs |", "| Sam Rivera | Own affairs |"), encoding="utf-8")
        # a note outside Personal that names a walled client's person in full
        write(self.root / "Zones" / "Work" / "Northwind" / "Threads" / "Pricing" / "Notes.md",
              "# Notes\n\nDana Whitlock asked for the figures.\n")
        self.commit(self.root, "the 0.59 context")
        # until the names branch lands, load_context() gives no owner: the tests that need one are given it
        lib = test_update.update.install.lib()
        real = lib.load_context

        def with_owner(root):
            ctx = real(root)
            if "owner" not in ctx:
                ctx["owner"] = {"name": "Sam Rivera", "first": "Sam"}
            return ctx
        from unittest import mock
        patch = mock.patch.object(lib, "load_context", with_owner)
        patch.start()
        self.addCleanup(patch.stop)
        self.real_load_context = real

    def study(self):
        import migrate_walls
        return migrate_walls.study(self.root, test_update.update.install.lib())

    def owner(self):
        ctx = self.real_load_context(self.root)
        if "owner" not in ctx:
            self.skipTest("garrick_lib's load_context() has no owner until the names branch is merged")
        return ctx["owner"]

    def test_the_owner_comes_from_load_context(self):
        self.assertEqual("Sam Rivera", self.owner()["name"])
        self.context.write_text(self.context.read_text().replace("Sam Rivera. Independent", "<Your name>. Independent"))
        self.assertFalse(self.owner())

    def test_a_party_named_after_the_owner_is_proposed_renamed(self):
        found = self.study()
        self.assertEqual({"jo": "Own affairs"}, found["prop"]["renames"])
        self.assertIn("| `jo` | yes | Own affairs |", found["text"])
        self.assertTrue(any("named after you" in n for n in found["prop"]["notes"]))
        import migrate_walls
        text = migrate_walls.rewrite(self.context.read_text(), found["prop"])
        self.assertIn("| Own affairs | Own affairs | Personal | `jo` | yes |", text)
        self.assertNotIn("| Sam Rivera |", text)

    def test_a_party_with_another_name_is_not_renamed(self):
        self.context.write_text(self.context.read_text().replace("| Sam Rivera | Own affairs |", "| Jo Example | Own affairs |"))
        self.assertEqual({}, self.study()["prop"]["renames"])

    def test_two_owner_named_parties_never_get_the_same_label(self):
        import migrate_walls
        lib = test_update.update.install.lib()
        ctx = lib.load_context(self.root)
        ctx["owner"] = {"name": "Sam Rivera", "first": "Sam"}
        ctx["parties"]["sam2"] = dict(ctx["parties"]["jo"], zone="Personal")
        ctx["parties"]["sam3"] = dict(ctx["parties"]["jo"], zone="Personal")
        ctx["parties"]["jo"]["party"] = ctx["parties"]["sam2"]["party"] = ctx["parties"]["sam3"]["party"] = "Sam Rivera"
        ctx["parties"]["sam2"]["flag"] = ctx["parties"]["sam3"]["flag"] = ""
        renames = migrate_walls.propose(self.root, lib, ctx)["renames"]
        self.assertEqual({"jo", "sam2", "sam3"}, set(renames))
        self.assertEqual(3, len(set(v.casefold() for v in renames.values())), renames)

    def test_a_check_that_cannot_run_is_unknown_not_clean(self):
        import migrate_walls
        from unittest import mock
        prop = migrate_walls.propose(self.root, test_update.update.install.lib(), test_update.update.install.lib().load_context(self.root))
        bad = mock.Mock(stdout="", stderr="boom", returncode=2)
        with mock.patch.object(migrate_walls.subprocess, "run", return_value=bad):
            self.assertIsNone(migrate_walls.refused_with(self.root, prop))
        self.assertIn("could not run", migrate_walls.say_refused(None))
        self.assertNotIn("refuses no file", migrate_walls.say_refused(None))

    def test_the_report_runs_the_check_that_ships_with_this_garrick(self):
        import migrate_walls
        from unittest import mock
        lib = test_update.update.install.lib()
        prop = migrate_walls.propose(self.root, lib, lib.load_context(self.root))
        ok = mock.Mock(stdout='{"findings": []}', stderr="", returncode=0)
        with mock.patch.object(migrate_walls.subprocess, "run", return_value=ok) as run:
            self.assertEqual([], migrate_walls.refused_with(self.root, prop))
        ran = run.call_args[0][0][1]
        self.assertEqual(str(Path(migrate_walls.__file__).resolve().parent / "check.py"), ran)
        self.assertNotIn(str(self.root / "System" / "tools"), ran)

    def test_the_write_path_skips_the_refusal_list(self):
        found = migrate_walls_study_without_list(self)
        self.assertIsNone(found["refused"])
        self.assertNotIn("walls check", found["text"])

    def test_the_report_lists_the_files_a_name_would_refuse(self):
        found = self.study()
        self.assertTrue(found["refused"], "the check run with the flags finds the walled client's person in a Work note")
        self.assertTrue(any("Northwind/Threads/Pricing/Notes.md" in f for f in found["refused"]), found["refused"])
        self.assertIn("would refuse", found["text"])
        self.assertIn("Notes.md", found["text"])
        self.assertTrue(self.context.read_text().count("## Walls"), "the study writes nothing")


def migrate_walls_study_without_list(case):
    import migrate_walls
    return migrate_walls.study(case.root, test_update.update.install.lib(), refused=False)


if __name__ == "__main__":
    unittest.main()
