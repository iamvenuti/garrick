---
concept: Handle
issue: https://github.com/iamvenuti/garrick/issues/698
---

# Handle

**The concept.** A handle is a short token that each remote answer carries so that record ids and retries from one chat stay apart, valid only while the grant's reach is the one it was made under.

**What it touches.** It touches Reach and Grant. It is an aid for the honest mistake of an old chat that carries on after the owner changed a reach, and it is not a wall: a model can ask for a new one.

**What was measured.** Tests: a made-up, an expired and a handle used after a reach change are each refused with the words start a new chat.

**What would show it is wrong.** A handle that works after the reach changed, or a page that calls a handle a boundary.
