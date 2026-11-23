---
concept: The morning brief
issue: https://github.com/iamvenuti/garrick/issues/686
---

# The morning brief

**The concept.** With one summary chosen for all zones, the nightly sweep sends one message after every zone has swept: what needs you today across the zones, ranked by `next_up.py`'s six rules, eight lines at most, then each zone's count of the rest. It replaces the zone-by-zone Todo summaries for the zones it covers, so the ranking the band already does is not done again in your head each morning.

**What it touches.** *`Todo.md`*, whose lines it reads through the todo skill's one reader; the band's ranking (`next_up.py`), which it says as one message and never re-sorts; the notifier (`notifications.py`), where it is the `morning-brief` event, follows the Todo summary's switch and is held through quiet hours as that summary is; and the sweep (`todo_sweep.py --digest`), which sends it. It names zone, thread and what is due, as the band's `say` does, and adds no word of a note, a Todo line or a meeting beyond that.

**What was measured.** Tests hold the brief's first line to the band's first pick at the same moment, its lines to the ranking in order, the cap and the counts, the quiet-day line, the failed-zone line, and that no note text, meeting text or Todo quotation reaches it. Nothing was measured on whether one ranked message is read more than four lists: that waits for use.

**What would show it is wrong.** People switching back to one summary for each zone, or a brief whose first lines are not what they act on first. The first would make "each" the default again; the second would send us to the ranking rules, which the band shares.

**Choices to know.** Absent `morning` reads `"each"`, so an existing workspace keeps its summaries; only a new workspace's setup writes `"all"`, and the update never does. A zone with a route of its own is left out and keeps its own summary: with `GARRICK_NOTIFY` or `GARRICK_NOTIFY_CMD` set for the sweep (a command that is told each zone), no brief is sent at all; a zone named under an older settings file's `notifications.zones` keeps its own. The cap is the sweep's `--brief-lines` (8), set in the job's plist beside `--digest`, not a Settings row. The Meetings inbox, which belongs to no zone, is in the brief as it is in the band.
