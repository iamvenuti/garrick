---
concept: The parked-thread hint
issue: https://github.com/iamvenuti/garrick/issues/664
---

# The parked-thread hint

**The concept.** `extras/hooks/parked_hint.py` adds one line of context when a prompt names a parked thread, its spoken form, its party or a person of that party. It gives back what the pointer did while it was in the index: a session could notice that a request was about a parked thread.

**What it touches.** It sits beside the waiting hook and the zone guard in `extras/hooks/`, and reads the zones' flags and the hub and thread notes' frontmatter. It names only threads of the session's own zone, of an open zone, or of any zone from the workspace root, and never says that a thread of another walled zone exists.

**What was measured.** A test on a workspace of 200 threads, with a margin, for the 5-second timeout; a test for every pair of walled zones, that a session in one never names a thread of the other; a test that no word of the prompt is written anywhere. Nothing was measured on how often a hint is right: that waits for use.

**What would show it is wrong.** A hint that names a thread across a wall, or a hint that fires so often that a user turns the hook off. The first would take the hook out at once; the second would make us tighten the match.

**Choices to know.** A session at the workspace root, or in `System/`, is told of a parked thread of any zone: those sessions belong to no zone, and the zone guard treats them so. A session in a wiki is told of open zones only. The cache in `System/generated/parked-hints.json` holds every zone's parked names, statuses and party people; it stays on this machine and git leaves it out, and what a session is told is filtered after it is read. A thread folder that is a link into another zone is skipped, so a link cannot give a zone another zone's names. The hook is registered by hand, as the waiting hook is: `install.py` writes no hook settings.
