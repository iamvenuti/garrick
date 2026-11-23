"""The memory index's budget and Nurture's parked pointer kind (#664).

    cd tests && python3 -m unittest test_memory_budget

Run in a workspace the installer made, with a memory folder of its own in the temporary folder. Nothing reads this Mac.
"""

import sys
import unittest

sys.dont_write_bytecode = True

from test_memory_pointer import Memory, INDEX  # noqa: E402
import check  # noqa: E402
import nurture  # noqa: E402


class TheBudget(Memory):
    def findings(self):
        return [f for f in check.run_checks(self.root, quick=True) if f.check == "memory" and "memory index" in f.message]

    def set_status(self, thread, status):
        path = self.work / "Acme" / "Threads" / thread / (thread + ".md")
        path.write_text(path.read_text().replace("status: active", "status: " + status, 1))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "%s %s" % (thread, status))

    def test_an_index_inside_its_budget_says_nothing(self):
        self.assertEqual([], self.findings())

    def test_an_index_over_8000_characters_gives_one_warning_that_names_its_longest_lines(self):
        self.index.write_text(INDEX + "".join("- [Pad %d](cedar.md) - %s\n" % (i, "x" * 100) for i in range(80)))
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertEqual("warning", found[0].severity)
        self.assertIn("characters, and the most is 8,000", found[0].message)

    def test_a_line_over_160_characters_gives_one_warning_naming_the_line_and_its_length(self):
        long = "- [Cedar](cedar.md) - " + "y" * 150 + "\n"
        self.index.write_text(INDEX + long)
        found = self.findings()
        self.assertEqual(1, len(found))
        self.assertIn("1 line over 160 characters; the longest: line %d (%d characters)" % (
            len(INDEX.split("\n")), len(long) - 1), found[0].message)
        self.assertNotIn("yyyy", found[0].message)             # the lines' text is not repeated

    def test_the_warning_names_the_pointers_of_parked_and_done_threads_still_in_the_index(self):
        self.index.write_text(INDEX + "- [Long](cedar.md) - " + "z" * 160 + "\n")
        self.set_status("Pricing", "parked")
        self.set_status("Freight", "done")
        message = self.findings()[0].message
        self.assertIn("2 pointers of a thread that is parked or done are still in it: acme-freight.md, acme-pricing.md", message)

    def test_with_no_memory_setting_the_index_is_not_read(self):
        self.index.write_text(INDEX + "- [Long](cedar.md) - " + "z" * 200 + "\n")
        self.settings(memory=[])
        self.assertEqual([], self.findings())


class TheKind(TheBudget):
    def kind_items(self):
        ctx = nurture.Ctx(self.root)
        return ctx, [i for i in nurture.gather(ctx, []) if i.kind == "parked-pointer"]

    def test_a_parked_or_done_threads_line_is_a_mechanical_fix_and_nothing_else_is_offered(self):
        self.assertEqual([], self.kind_items()[1])
        self.set_status("Pricing", "parked")
        self.set_status("Freight", "done")
        items = self.kind_items()[1]
        self.assertEqual(["acme-freight.md", "acme-pricing.md"], sorted(i.fix["file"] for i in items))
        self.assertEqual("parked-pointer", nurture.KINDS["parked-pointer"].name)
        self.assertIsNotNone(nurture.KINDS["parked-pointer"].apply)

    def test_applying_it_moves_the_file_and_the_line_deletes_nothing_and_commits_nothing(self):
        self.set_status("Pricing", "parked")
        self.set_status("Freight", "done")
        head = self.git("rev-parse", "HEAD").stdout
        ctx, items = self.kind_items()
        done = nurture.apply(ctx, items)
        self.assertEqual(2, len(done["fixed"]))
        self.assertEqual([], done["held"])
        self.assertEqual(["acme-freight.md", "acme-pricing.md"], sorted(p.name for p in (self.mem / "parked").glob("*.md")))
        self.assertNotIn("acme-", self.index.read_text())
        self.assertEqual(head, self.git("rev-parse", "HEAD").stdout)
        self.assertEqual([], done["commits"])
        self.assertEqual([], self.kind_items()[1])

    def test_a_name_clash_in_parked_holds_the_fix(self):
        self.set_status("Pricing", "parked")
        (self.mem / "parked").mkdir()
        (self.mem / "parked" / "acme-pricing.md").write_text("kept\n")
        ctx, items = self.kind_items()
        done = nurture.apply(ctx, items)
        self.assertEqual([], done["fixed"])
        self.assertEqual(1, len(done["held"]))
        self.assertEqual("kept\n", (self.mem / "parked" / "acme-pricing.md").read_text())

    def test_the_nightly_run_never_applies_it(self):
        self.set_status("Pricing", "parked")
        ctx = nurture.Ctx(self.root, headless=True)
        items = [i for i in nurture.gather(ctx, []) if i.kind == "parked-pointer"]
        self.assertEqual(1, len(items))
        done = nurture.apply(ctx, items)
        self.assertEqual([], done["fixed"])
        self.assertTrue((self.mem / "acme-pricing.md").is_file())


if __name__ == "__main__":
    unittest.main()
