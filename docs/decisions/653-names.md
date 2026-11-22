---
concept: System/names.md
issue: https://github.com/iamvenuti/garrick/issues/653
---

# System/names.md

**The concept.** `System/names.md` holds the People and Aliases tables, so that `System/context.md`, which every session loads, stays short.

**What it touches.** It sits beside People, Aliases and `System/context.md`, and the update's held step moves the two tables there on the user's yes.

**What was measured.** A workspace used for a few months had a `System/context.md` of about 16,000 characters, of which about 8,500 were the People and Aliases tables. After the move a context file of the example workspace is under 8,000 characters, and so is one with about 90 invented people; a test builds both. Nothing was measured on how often a session reads the new file: that waits for a later issue.

**What would show it is wrong.** A session that is given a mangled name and does not read `System/names.md` before acting, measured on a workspace in each assistant. Or a user who finds that a moved workspace loses a row. Either one would make us put the tables back.
