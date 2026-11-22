---
concept: Usage counts
issue: https://github.com/iamvenuti/garrick/issues/651
---

# Usage counts

**The concept.** The Mac app counts which of the page's cards are opened, by card id and day, on this Mac only.

**What it touches.** It sits beside *The Garrick App*, whose cards it counts, and *View model*, which holds the set of card ids. It adds one file under `System/`, which is never committed, and one setting, on by default. It touches no zone and no wiki.

**What was measured.** Nothing yet: the count exists to measure. Tests hold what it can store (an id, a day and a count, built only from checked values), that a name, a path or text is refused with nothing written, that off writes nothing, and that a file not in the writer's own shape is not read into the next.

**What would show it is wrong.** A count file that holds anything but a card id, a day and a number; a count taken while the setting is off; or a report whose figures do not match the opens that were made.
