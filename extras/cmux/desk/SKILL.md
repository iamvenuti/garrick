---
name: desk
description: >
  Open, close and wrap the cmux tabs the user works in, one per thread, by
  voice. Installed with the cmux extra. Use when the user says "open X",
  "start a session on X", "new tab for X", "close X", "close the X tab",
  "close for the day", "I'm done for today", "shut everything down", "start
  the day", "restore my tabs", "bring everything back", "what tabs are open",
  "new workspace X", or asks to take up where they left off. Where this skill
  is installed it takes these phrases first; the session in each tab runs the
  threads skill.
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
desk colour [ZONE...]            # each zone's workspace in its colour from the status page's Settings
desk status --today --json       # the tabs used today, for a script: session id, folder, thread note
desk wrap X [--yes]              # X's session wraps its thread; the tab stays open
```

desk quits nothing and restores nothing. cmux resumes each tab's agent session
itself when it reopens (its setting `terminal.autoResumeAgentSessions`, on by
default).

If `desk` is not on the PATH, run `python3 <garrick>/extras/cmux/desk.py`
with the same arguments, where `<garrick>` is the Garrick download.

## What the user says

| The user says | Run | Then |
|---|---|---|
| "open X", "start a session on X" | `desk open X --prompt "open X"` | The session in the tab answers in two sentences. Already open: desk brings it forward and sends the phrase only if the tab is idle. Say which tab it was. |
| "close X" | `desk close X --wrap`, read it back, then `desk close X --wrap --yes` | X's own session wraps the thread, then the tab closes. |
| "close the X tab" | `desk close X`, read it back, then `--yes` | Closes without a wrap. |
| "close for the day", "I'm done for today" | The threads skill's *Close for the day* | Each session used today wraps its own thread, one at a time. The cmux tabs come from `desk status --today --json` and are asked with `desk wrap --session ID --yes`; sessions outside cmux are the threads skill's step. Nothing is quit. |
| "back", "where was I", "back to X" | The threads skill's Back, then `desk open "<its folder>" --prompt "open X"` | The threads skill picks the live thread whose note was written most recently; its tab comes forward and the session there reads back where the user was. |
| "shut everything down" | Nothing to run | Say that Cmd+Q quits cmux, and that every tab comes back in its session when cmux opens. To wrap first, "close for the day". |
| "start the day", "restore my tabs", "bring everything back" | Nothing to run | Open cmux: each tab that ran an agent comes back in that agent's session. A tab at a bare prompt means cmux never quit (its process survived Cmd+Q): check with `pgrep -l cmux`, quit it for real, and open it again. |
| "what tabs are open" | `desk status` | Spoken: how many, then the busy ones by name. |
| "new workspace X" | `desk workspace X` | |

**The tabs, in the rules' words.** Where the desk skill is installed (the cmux extra), each thread has a tab of its own and the session in it holds the thread's conversation. "Open X" opens or brings forward X's tab, and the session there answers. "Close X" has that session wrap X, then closes the tab; "close the X tab" closes it without a wrap. "Close for the day" has every session used today wrap its own thread, and quits nothing. "Start the day" is opening cmux, which resumes its tabs itself, and "what tabs are open" lists them.

`--yes` and `--force` are the user's to give, never yours. Read the dry run
back first.

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

`close` finds an open tab by its whole name or folder, or by a part of one at
least four letters long that no other tab shares. When it refuses a short or
shared part, ask which tab in one line.

## Busy, idle and unknown

A tab's state is read from its assistant's transcript, never from its title:
Claude Code ends a turn with a `turn_duration` or `stop_hook_summary` record
(`local_command` for a slash command), Codex with `task_complete` or
`turn_aborted` for the same turn. A tab whose transcript is missing or
unreadable is `?`. The exception is `empty`: a Claude Code tab with no
prompt since it started or was cleared with `/clear`, which has no
transcript yet and which Claude Code's own session record shows idle. It
counts as idle with nothing to wrap: `close` closes it without a wrap,
`close --wrap` and `wrap` refuse or skip it, and `status --today` leaves it out.

- `close` refuses a tab that is busy or `?`, and closes nothing when it does.
- `wrap` wraps one tab at a time, because wraps write shared files. The wrap
  has 90 seconds to start and 15 minutes to finish, and desk waits for the
  turn to end and for the wrap's lock to go. It says whether the thread's
  wrap record (`System/generated/wrap-<note>.done`) was written.
- Each tab is checked again the moment its wrap is sent. One that has started
  a turn since, or stopped on a question, gets nothing typed into it: the
  wrap's Enter would answer the question. `wrap` skips it, names it and exits
  3; `close --wrap` leaves it open.

## Settings

`System/desk.json`, all optional (`desk.example.json` beside the script shows
each): `workspaces` (the cmux workspace for each zone, and `neutral` for
System and the wikis), `skip` (folder names to pass over), `aliases`, `agent`
(`claude` or `codex`) and `socket_password_file`. `before_quit` is retired: `update` moves its commands into `System/jobs/nightly.local`.
