"""Nurture and a mixed project (#632): a one-job project with a thread that keeps `Sources/` or `Deliverables/` of its own is a
mechanical finding, and one yes runs the Join (`scaffold.py layout --join`) in its zone, in one commit. A name the project has
already is the owner's to place, so it is held and nothing moves. The nightly run leaves it.

    cd tests && python3 -m unittest test_nurture_join
"""

from __future__ import annotations

import shutil
import sys
import unittest

sys.dont_write_bytecode = True

from fixtures import git, project_hub, thread_note, write  # noqa: E402
from garrick_lib import WALL_HOOK_MARK  # noqa: E402
from test_nurture import Base  # noqa: E402


class MixedProject(Base):
    def setUp(self):
        super().setUp()
        hook = self.work / ".git" / "hooks" / "pre-commit"            # a zone's hook as scaffold asks for it: marked, and runnable
        write(hook, "#!/bin/sh\n# %s\nexit 0\n" % WALL_HOOK_MARK)
        hook.chmod(0o755)
        self.freight = self.acme / "Threads" / "Freight"
        write(self.freight / "Sources" / "brief.txt", "the brief\n")
        write(self.freight / "Deliverables" / "260201 - Freight plan.docx", "plan\n")
        self.commit(self.work, "2026-10-01T10:00:00")

    def joins(self, out=None):
        items = (out or self.run_tool("list")[1])["items"]
        return [i for i in items if (i.get("fix") or {}).get("op") == "join-papers"]

    def threads_with_papers(self):
        return [t.name for t in (self.acme / "Threads").iterdir() if (t / "Sources").exists() or (t / "Deliverables").exists()]

    def test_the_finding_is_mechanical_and_names_the_files_it_would_move(self):
        (item,) = self.joins()
        self.assertEqual("mechanical", item["kind"])
        self.assertEqual("Zones/Work/Acme Review/Acme Review.md", item["path"])
        self.assertIn("Zones/Work/Acme Review/Threads/Freight/Sources/brief.txt", item["touches"])
        self.assertIn("Zones/Work/Acme Review/Sources/brief.txt", item["touches"])
        self.assertEqual(["Zones/Work/Acme Review"], item["where"])

    def test_one_yes_leaves_no_thread_folder_with_papers_in_one_commit_of_its_own(self):
        before = self.log(self.work)
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual([], self.threads_with_papers())
        self.assertEqual("the brief\n", (self.acme / "Sources" / "brief.txt").read_text())
        self.assertTrue((self.acme / "Deliverables" / "260201 - Freight plan.docx").is_file())
        self.assertIn("join-papers", {i["fix"]["op"] for i in out["fixed"]})
        moved = [c for c in out["commits"] if "layout" in c["message"]]
        self.assertEqual(1, len(moved))
        self.assertIn("Garrick-Moved-Files: 2", git(self.work, "show", "-s", "--format=%B", moved[0]["commit"]))
        self.assertGreater(len(self.log(self.work)), len(before))
        self.assertEqual([], self.joins())

    def test_a_clash_is_held_and_nothing_moves(self):
        write(self.acme / "Sources" / "brief.txt", "the project's own brief\n")
        self.commit(self.work, "2026-10-02T10:00:00")
        self.assertEqual([], self.joins())                            # the plan lists a file to place: no one-yes fix is offered
        mixed = [i for i in self.run_tool("list")[1]["items"] if "is one job, but the thread" in i["message"]]
        self.assertEqual(["judgment"], [i["kind"] for i in mixed])    # still reported, for the owner to place
        self.assertIn("yours", mixed[0]["held"])
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual(["Freight"], self.threads_with_papers())
        self.assertEqual("the brief\n", (self.freight / "Sources" / "brief.txt").read_text())
        self.assertEqual("the project's own brief\n", (self.acme / "Sources" / "brief.txt").read_text())
        self.assertNotIn("join-papers", {i["fix"]["op"] for i in out["fixed"]})
        self.assertFalse([s for s in git(self.work, "log", "--format=%s").splitlines() if "layout" in s])

    def test_a_project_whose_papers_folder_is_a_link_into_another_zone_is_held_and_nothing_moves(self):
        elsewhere = self.root / "Zones" / "Personal" / "Elsewhere"     # G26: the project's Deliverables/ is a link into Personal
        elsewhere.mkdir(parents=True)
        shutil.rmtree(self.acme / "Deliverables", ignore_errors=True)
        (self.acme / "Deliverables").symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual([], self.joins())                            # the plan refuses the move: no one-yes fix is offered
        code, out = self.run_tool("fix", "--yes")
        self.assertEqual([], list(elsewhere.iterdir()))               # nothing reached the other zone
        self.assertTrue((self.freight / "Deliverables" / "260201 - Freight plan.docx").is_file())
        self.assertTrue((self.freight / "Sources" / "brief.txt").is_file())
        self.assertNotIn("join-papers", {i["fix"]["op"] for i in out["fixed"]})
        self.assertFalse([s for s in git(self.work, "log", "--format=%s").splitlines() if "layout" in s])

    def test_the_nightly_run_leaves_it(self):
        code, out = self.run_tool("nightly")
        self.assertEqual(0, code, out)
        self.assertNotIn("join-papers", {i["fix"]["op"] for i in out["fixed"]})
        self.assertEqual(["Freight"], self.threads_with_papers())

    def test_a_project_in_another_zone_is_untouched(self):
        other = self.root / "Zones" / "Personal" / "Garden"
        write(other / "Garden.md", project_hub("Personal", "Garden", "personal", ["Beds"]))
        write(other / "Threads" / "Beds" / "Beds.md", thread_note("Garden", "Beds", "personal"))
        write(other / "Threads" / "Beds" / "Sources" / "seeds.txt", "seeds\n")
        code, out = self.run_tool("fix", "--yes", "--scope", "Zones/Work")
        self.assertEqual("seeds\n", (other / "Threads" / "Beds" / "Sources" / "seeds.txt").read_text())
        self.assertFalse((other / "Sources" / "seeds.txt").exists())
        self.assertEqual([], self.threads_with_papers())              # its own zone's project was joined
        self.assertFalse((self.acme / "Sources" / "seeds.txt").exists())


if __name__ == "__main__":
    unittest.main()
