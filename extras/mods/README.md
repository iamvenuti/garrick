# Extra: the Garrick band, a Claude Code mod

A session opened in a thread folder doesn't know where it is until the assistant has read the thread note. That takes a turn, and the answer scrolls away. When the assistant names a file in a reply, the path is plain text, so you go to Finder and look for it. `garrick-band` fixes both in Claude Code, and spends no tokens until you press one of its buttons.

It is Claude Code only, and optional. Core Garrick never depends on it. It displays what your notes already say and enforces nothing, so a Codex session misses only the display.

## What it shows

Above the prompt, two lines beside the mark:

```
█ ▀▀  Garrick · Work › Acme › Pricing active · 42%
█ ██  Wrap  Clear  Finder  Obsidian
```

- The Garrick mark, a 4×2 tile of terminal cells drawn with half blocks, as tall as the two lines, so the terminal needs no image support.
- `Garrick · <Zone> › <Project> › <Thread>`, with the note's `status` in colour: green for active, yellow for parked, grey for done. Then how full the context window is, as a whole percentage: dimmed up to 60%, red above it, the point where it is time to wrap and clear. It is the status line's own figure, from the mods API's plain usage call, which costs nothing and counts no tokens, and it is read again after every turn. Before a session's first reply, from *Clear* or `/clear` until the new conversation's first reply, and just after a compaction, there is no figure yet, and the band shows none.
- A row of buttons, all at one weight. Click one, or press ctrl+x tab to reach the band and then its letter:
  - *Wrap* (`w`) asks the assistant to rewrite the Resume here block and add today's dated entry, the rules' "wrap X". A finished thread has no Wrap.
  - *Clear* (`c`) runs `/clear`, which starts a new conversation in the same folder. The band stays. `/resume` brings back the conversation you cleared.
  - *Finder* (`f`) shows the thread note in Finder, on a Mac.
  - *Obsidian* (`o`) opens the thread note in Obsidian. It is offered only when Obsidian is installed and the note sits in a vault, so a folder like `System/`, which is not a vault, gets no Obsidian.

  *Finder* and *Obsidian*, here and in the Resume here pane, follow Settings › Opening a thread on the [status page](../../docs/extras/status-page.md#settings): *Obsidian* only while *Open in Obsidian* (`note`) is switched on, *Finder* only while *Reveal in Finder* is. The band reads `launchers` in `System/garrick-settings.json` when the session starts and after every turn. With no `launchers` saved, or a file that does not read, both are offered as above.

  At a project whose hub has no Resume here block because each thread keeps its own, *Wrap* asks the assistant to wrap the thread this session worked on, and the hub too if its status changed. When the session touched no thread, it says so and stops. `/garrick resume` asks where each live thread stands, and `/garrick note` shows every live thread's block. Parked and done threads are left out.

  Where there is no thread note above the folder, such as `System/`, the workspace root or a wiki, there is nothing to resume, wrap or show, so the band offers *Clear* and *Finder*, which shows the folder. In a wiki, *Obsidian* opens its `wiki/index.md`.

The band does not repeat what the session already shows: no Resume here paragraph, and no echo of your last prompt or the step the assistant is on.

Outside any project it shows the mark and where you are, such as `System` or `Wikis › Meetings`. It reads the note again after every turn, so a wrap shows up straight away.

The `[-]` at the band's right end is Claude Code's own: it folds the band, and `[+]` or ctrl+x ctrl+a opens it again. `/garrick hide` takes the band away altogether, and `/garrick` brings it back. `/garrick` always shows the band and never toggles it, because a mod cannot tell whether Claude Code has the band folded. It also works while a turn runs. `/garrick wrap`, `/garrick finder` and `/garrick obsidian` do what the buttons do, and bring back a hidden band. With the launcher switched off in Settings, `/garrick obsidian` answers "Obsidian is switched off in Settings › Opening a thread." and opens nothing, and `/garrick finder` the same for Finder. Two more have no button:

- `/garrick resume` asks the assistant to read the Resume here block and say where the thread stands and what comes next, the rules' "Open X", as saying "open X" does. You get the answer in the conversation, where you can carry on from it.
- `/garrick note` shows the whole Resume here block of the thread note in a pane. It reads the file and sends nothing to the model. The pane draws it as a reply is drawn, with tables and emphasis, and wikilinks and file paths become links that a click opens. Its *Open in Obsidian* and *Reveal in Finder* show the whole note.
`/garrick next`, `open`, `tick` and `later` act on [While you wait](#while-you-wait-a-preview-feature), a preview feature.

In the assistant's replies, a path in backticks becomes a link, so Cmd-click opens the file in its default app, or a folder in Finder:

- A span counts as a path when it has a `/` or a file extension, so `claude plugin test` stays plain. Code fences are left alone.
- Absolute and `~/` paths link when the file exists. Anything else is matched against an index of the workspace: a full path, a partial one (`Deliverables/x.xlsx`) or a bare file name. When two files match, the one under the session's folder wins; otherwise the span stays plain, so you never get a dead link.
- The index is one `find` over the workspace when the session starts and after every turn. It skips `.git`, `.obsidian`, `node_modules`, `__pycache__` and `.trash`, and `find` doesn't follow symlinks, so a cloud folder linked into the workspace is never walked.
- Only the drawing changes. The stored reply keeps its plain text.

How it finds the note: from the folder the session started in (a `cd` the assistant runs in a command does not move it) it walks up to the workspace root, the first folder holding `System/rules.md`. The first folder on the way that holds a note with its own name, `<Folder>/<Folder>.md`, is the thread or project. To show the band it only reads files and the usage figure, and never calls a model. *Wrap* and `/garrick resume` send a prompt in your name, only when you ask. It runs these processes: that `find`; `open` when you press *Finder* or *Obsidian*; and, with While you wait switched on, `python3` on `System/tools/next_up.py`, which only reads, and on `System/status/page_action.py` when you open or tick a suggestion.

## While you wait, a preview feature

While you wait is parked: it is off unless you switch it on in `System/garrick-flags.json`, as the status page's [preview features](../../docs/extras/status-page.md#preview-features) are:

```json
{"while-you-wait": true}
```

The band reads the file at the start of each turn. Off, it shows no suggestion line, and `/garrick next`, `open`, `tick` and `later` answer that While you wait is a preview feature and is off. Saying "what's next" works either way: the `threads` skill runs the same script.

A long turn, a wrap, an ingest or a build, can run for minutes. With the feature on, once a turn has run longer than a threshold, 45 seconds unless you change it, one line appears above the buttons with one thing worth doing elsewhere in those minutes:

```
While you wait: Renewal: Reply on the renewal dates (Work, due today) /garrick open next tick later
```

It comes from `System/tools/next_up.py`, which ranks by six plain rules and asks no model: the top of the interruption stack (with the [status page](../../docs/extras/status-page.md) extra, which keeps it), Todo lines due today or late, a reply or a chase before a line that names a deliverable, chases that have come due, what waits in an Inbox, a parked thread left alone for 30 days ("Park or finish?"), and a live thread not wrapped for 14 ("Wrap?"). A suggestion names a thread and an action in a few words, never quotes a meeting, and never names the thread the session is in. It is drawn from every zone unless *Same zone only* is on.

Four words act on it, typed as `/garrick next`, `/garrick open`, `/garrick tick` and `/garrick later`, which run at once while the turn goes on, or clicked on the line:

- *next* shows the following suggestion. The band reads the list once when the line appears, and again on *next* only when that answer is more than a minute old.
- *open* opens it elsewhere, the way Settings › Opening a thread says: the default first, then the first of the others switched on that the band can run here, cmux, the note, Finder, in that order. *Open in cmux* is the thread's own cmux tab with the [desk](../../docs/extras/cmux.md), and an Inbox opens a tab on "process the inbox"; *Open in Obsidian* is the note in Obsidian when it sits in a vault; *Reveal in Finder* shows the note in its folder, or an Inbox's folder. Codex and Claude are not among them. When none switched on can open it, it says so and opens nothing. With no `launchers` saved, it goes as before Settings had the section: the cmux tab, else the note in Obsidian, else the Mac's default app.
- *tick* ticks a Todo line through the status page's `page_action.py`, as the page does, committed in its zone. A tick in the zone the turn is working in waits for the turn to end, so the two commits never meet, and the band says so; a session outside any zone holds every tick.
- *later* puts the line away for this turn.

None of them sends anything to the running session. When the turn ends, the line goes, and a toast says the turn has finished and what any held tick did.

The letter keys of the band's own buttons are not used for these. Whether a band's keys fire while a turn runs is not something the mods API promises, and `o` is already *Obsidian*; `/garrick` is registered to run mid-turn, so the words are the way that works.

Settings › While you wait, on the status page while the flag is on, switches it on or off and sets the threshold, *Same zone only*, which sources count and in what order, and how old a parked or an unwrapped thread must be. They are kept in `System/garrick-settings.json` under `while-you-wait`, which the band reads at the start of each turn. In a session without the band, ask "what's next": the `threads` skill runs the same script, so the answer is the band's first pick.

## Load it

You need Claude Code 2.1.289 or later. This version was tested on 2.1.295. The mods API is new and may change between Claude Code releases.

To try it in one session:

```sh
claude --plugin-dir /path/to/garrick/extras/mods/garrick-band
```

To load it in every session, add it to the `env` block of `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "/path/to/garrick/extras/mods/garrick-band"
  }
}
```

Point it at the folder of the Garrick download you keep. When you replace that download with a newer one, the next session loads the new copy. The update command does not change it, since it lives outside your workspace, but its report names the band when the copy your settings point at differs from the newer Garrick's. To stop loading it, remove the line.

## Check it

From `extras/mods/`:

```sh
claude plugin validate garrick-band
claude plugin test garrick-band
```

The repository's test suite runs both when `claude` is installed, and CI runs them on the tested version.
