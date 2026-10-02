# Workspace

The entry point for any assistant working here, whatever its brand. Read `System/rules.md` and `System/context.md` before anything else. The first says how to behave, the second who is who. Each is the only copy of what it holds.

`AGENTS.md` is the only instruction file name in this workspace. Never create a `CLAUDE.md` anywhere under this folder: Claude Code stops reading every `AGENTS.md` once one exists.

## Layout

Three levels of work, two memories, one system folder.

| Path | Holds |
|---|---|
| `System/` | Rules, context, skills and checks. Everything else consumes it |
| `System/generated/` | Pages a tool rebuilds, such as the status page. Never committed; never edit them, never file anything here |
| `Zones/<Zone>/` | One side of life or work. Its own git repository |
| `Zones/<Zone>/<Project>/` | One client, engagement or undertaking. The hub note is named after it |
| `Zones/<Zone>/<Project>/Threads/<Thread>/` | One line of work, with one resume point |
| `Zones/<Zone>/Inbox/` | Mail and files waiting to be sorted. Not a project |
| `Wikis/Meetings/` | Every conversation and mail, from every zone. Who said what, and when |
| `Wikis/Knowledge/` | Published material you study. Usable anywhere |

## Where a question goes

Route every question by its subject, not by the folder the session happens to be open in or the one used last.

- "Where did we land with X", "what did Y say", "what do I owe them" → `Wikis/Meetings/`.
- "What is X", "what does the research say about Y" → `Wikis/Knowledge/`.
- "Where am I on X", "open X" → that thread's `Resume here` block.
- A question that could belong to two zones → ask which. Never pick one silently.

Every zone and wiki has its own `AGENTS.md`. Read it before working there, even if your assistant did not load it: each zone is its own git repository, and not every assistant looks inside one. It adds to this file and wins where it says so.

## Skills

`System/skills/<name>/SKILL.md` holds the procedures. List the folder to see what exists; each file opens with when it applies. An assistant that does not read skills on its own can still open the file and follow it by hand.

## What this file is not

It routes and points. It holds no status, no copy of another file, and no hand-kept list of projects or skills: those go stale here while the real ones move on. `System/tools/check.py` warns when it grows or copies.
