---
concept: The guard hooks check
issue: https://github.com/iamvenuti/garrick/issues/685
---

# The guard hooks check

**The concept.** The guard hooks check is one warning for each guard hook an assistant's settings name that is not this release's: another version's bytes, a path inside the workspace, or a path that does not exist. Between one update and the next, nothing else says that a guard has gone stale.

**What it touches.** It is a new check in `check.py`, beside the others, and reads only the two assistants' settings files and the hook files they name. It shares the hook path reader of #670 as a fourth copy, fed by the same test table. It writes nothing, blocks nothing, and changes neither the guards nor the wall check.

**What was measured.** Bytes only: each hook file's SHA-256 against this release's digests of `zone_guard.py` and `read_guard.py`, the same digests Settings holds, kept equal by a test. The fixtures are a kept download of this release, of an older release, one inside the workspace, a path that does not exist, and settings with no guard.

**What would show it is wrong.** A warning for a guard that is this release's, no warning for one that is not, a finding that shows the home folder or an environment variable's value, or a finding when no guard is registered.
