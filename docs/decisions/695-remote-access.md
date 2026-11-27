---
concept: Remote access
issue: https://github.com/iamvenuti/garrick/issues/695
---

# Remote access

**The concept.** Remote access is an optional extra that serves the workspace to an assistant on a phone or another computer, off until the owner turns it on at the Mac, and labelled a preview.

**What it touches.** It sits beside phone access, which uses the assistant provider's own remote features, and beside Ask, whose readers it reuses. It is the first part of Garrick that faces the internet, with its own Python runtime and a lock file with hashes. The core stays on the standard library and the wall check does not change.

**What was measured.** Counts and tests only: nothing listens on any interface but loopback, the runtime installs only from the lock, and a test client on the same computer drives sign-in, a read, a write and a refused walled zone. The real relay and a phone are not measured yet, and the page says so.

**What would show it is wrong.** A listener on any interface but loopback, a service that runs while remote access is off or paused, an install that takes a package outside the lock, or a log that holds a token, a code or a record's text.
