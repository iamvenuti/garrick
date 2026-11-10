"""correct.py reaches history files (#502): the reach only, as it reaches every other live note.

    cd tests && python3 -m unittest test_history_correct
"""

from __future__ import annotations

import sys
import unittest

sys.dont_write_bytecode = True

from test_history import FRONT, RESUME, TODAY, Fixture, day, entry, history, thread  # noqa: E402


class Correcting(Fixture):
    """correct.py reaches history files, as it reaches every other live note."""

    def test_a_correction_reaches_a_history_file(self):
        import correct
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]).replace("Entry 5 settled", "Entry 5 settled with Dana Whitlaw and"))
        self.assertTrue(history.apply(self.root, self.a, TODAY).done)
        hits = correct.find_hits(self.root, "Dana Whitlaw", "Dana Whitlock")
        kinds = {(h.kind, h.path.parent.name) for h in hits}
        self.assertIn(("history", "history"), kinds)
        done = correct.apply(self.root, "Dana Whitlaw", "Dana Whitlock", hits, commit=False, rebuild=False, today="2026-11-10")
        text = "\n".join(p.read_text(encoding="utf-8") for p in (self.a.parent / "history").glob("*.md"))
        self.assertIn("Dana Whitlock", text)
        self.assertNotIn("Dana Whitlaw", text)

    def test_the_places_name_the_history_files_of_a_hub_too(self):
        import correct
        hub = self.root / "Zones" / "Work" / "Northwind" / "Northwind.md"
        text = (FRONT % ("Northwind", "Northwind", "Northwind", "acme")).replace("type: thread", "type: project") + \
            RESUME % "Northwind" + "\n".join(entry(i, day(n)) for i, n in enumerate([1, 2, 3, 4, 5, 400]))
        self.put(hub, text)
        self.assertTrue(history.apply(self.root, hub, TODAY).done)
        found = [(k, p.name) for k, p in correct.places(self.root, memory=[]) if k == "history"]
        self.assertTrue([f for f in found if f[1].startswith("Northwind history ")], found)


class Links(Fixture):
    def test_a_history_folder_that_is_a_link_is_not_reached(self):
        import correct, os
        self.put(self.a, thread("Pricing", "Northwind", "acme", [1, 2, 3, 4, 5, 400]))
        elsewhere = self.root / "Zones" / "Home" / "Garden" / "elsewhere"
        elsewhere.mkdir(parents=True)
        (elsewhere / "x.md").write_text("Dana Whitlaw\n", encoding="utf-8")
        os.symlink(str(elsewhere), str(self.a.parent / "history"))
        self.assertEqual([], [p for k, p in correct.places(self.root, memory=[]) if k == "history"])


if __name__ == "__main__":
    unittest.main()
