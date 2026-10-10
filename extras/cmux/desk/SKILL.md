---
name: desk
description: >
  Open, close, wrap and bring back the cmux tabs the user works in, one per
  thread, by voice. Installed with the cmux extra. Use when the user says
  "open X", "start a session on X", "new tab for X", "close X", "close the X
  tab", "close for the day", "I'm done for today", "shut everything down",
  "start the day", "restore my tabs", "bring everything back", "what tabs are
  open", "new workspace X", or asks to take up where they left off. Where this
  skill is installed it takes these phrases first; the session in each tab
  runs the threads skill.
---

# Desk

One cmux tab per thread, each an assistant session started in that thread's
folder and named after it, grouped into one cmux workspace per zone. The
`desk` command does the plumbing; you turn what the user says into the right
verb. The session in each tab is where the thread's conversation lives, so
that session opens and wraps the thread, through the `threads` skill.

```sh
desk status                      # every live assistant tab: workspace, state, folder
desk open X --prompt "open X"    # X's tab, started on "open X"; an idle tab already there gets the phrase
desk open X --agent codex        # Codex instead of the default assistant
desk close X [--wrap] [--yes]    # close X's tab; --wrap has it wrap its thread first
desk workspace NAME              # a new workspace in cmux's sidebar
desk end [--yes]                 # check nothing is busy, then quit cmux
desk shutdown [--yes]            # wrap each tab used today, one at a time, then quit cmux
desk start                       # start or restore cmux, resume tabs that came back empty
```

If `desk` is not on the PATH, run `python3 <garrick>/extras/cmux/desk.py`
with the same arguments, where `<garrick>` is the Garrick download.

## What the user says

| The user says | Run | Then |
|---|---|---|
| "open X", "start a session on X" | `desk open X --prompt "open X"` | The session in the tab answers in two sentences. Already open: desk brings it forward and sends the phrase only if the tab is idle. Say which tab it was. |
| "close X" | `desk close X --wrap`, read it back, then `desk close X --wrap --yes` | X's own session wraps the thread, then the tab closes. |
| "close the X tab" | `desk close X`, read it back, then `--yes` | Closes without a wrap. |
| "close for the day", "I'm done for today" | `desk shutdown`, read it back, then `desk shutdown --yes` | Each tab used today wraps its own thread, then cmux quits. It ends this session too. |
| "shut everything down" | `desk end`, read it back, then `desk end --yes` | Quits without wrapping. Every tab comes back on `start`. |
| "start the day", "restore my tabs", "bring everything back" | `desk start` | Read back what came back and anything it could not find. |
| "what tabs are open" | `desk status` | Spoken: how many, then the busy ones by name. |
| "new workspace X" | `desk workspace X` | |

`--yes` and `--force` are the user's to give, never yours. Read the dry run
back first, and say everything you need to say before a quit: it lands three
seconds after `--yes` and takes this session with it.

**"Close X" from X's own tab.** This session is mid-turn while it runs `desk`,
so desk refuses to close it. Wrap here with the `threads` skill, then tell the
user the tab can be closed.

## Names

desk resolves a heard name as the `threads` skill does: an alias from the
Aliases table in `System/context.md` (and any in `System/desk.json`), then a
thread's name, then "project thread", then a project, a wiki or System, then a
part of a name, initials, and a name that sounds close. When it lists several,
ask which in one line, naming them. Never pick, and never pick between zones.

`open` refuses a folder that holds projects instead of being one: the
workspace root, `Zones/`, a zone's folder, `Wikis/`. A session there reaches
every project below it. The root opens only when named by its full path, for
work that files into every zone, such as processing the inboxes.

## Busy, idle and unknown

A tab's state is read from its assistant's transcript, never from its title:
Claude Code ends a turn with a `turn_duration` record, Codex with
`task_complete` or `turn_aborted` for the same turn. A tab whose transcript is
missing or unreadable is `?`.

- `close` refuses a tab that is busy or `?`, and closes nothing when it does.
- `shutdown` refuses while any tab is busy or `?`. With `--yes` it wraps one
  tab at a time, because wraps write shared files. Each wrap has 90 seconds to
  start and 15 minutes to finish; one that does not stops the shutdown with
  cmux still running, and a notification says which tab. Then the commands
  under `before_quit` in `System/desk.json` run, in order, from the workspace
  root, such as a backup. Progress goes to `desk-shutdown.log` in the jobs
  folder.
- `end` refuses a busy or `?` tab unless the user says `--force`.

## Bringing tabs back

Quitting keeps every tab in cmux's restore set; closing one takes it out. cmux
does not always bring the assistant back inside a tab, so every quit writes
`desk-snapshot.json` in the jobs folder: which session sat in which tab. `start`
waits until cmux has stopped reopening sessions, then types the assistant's own
resume command into each recorded tab that came back at a bare prompt. It never
types into a tab with an assistant in it, and a second run does nothing.

## Settings

`System/desk.json`, all optional (`desk.example.json` beside the script shows
each): `workspaces` (the cmux workspace for each zone, and `neutral` for
System and the wikis), `skip` (folder names to pass over), `aliases`, `agent`
(`claude` or `codex`), `before_quit` and `socket_password_file`.
