# Extra: the Garrick band, a Claude Code mod

A session opened in a thread folder doesn't know where it is until the assistant has read the thread note. That takes a turn, and the answer scrolls away. When the assistant names a file in a reply, the path is plain text, so you go to Finder and look for it. `garrick-band` fixes both in Claude Code, and spends no tokens until you press one of its buttons.

It is Claude Code only, and optional. Core Garrick never depends on it. It displays what your notes already say and enforces nothing, so a Codex session misses only the display.

## What it shows

Above the prompt, two lines beside the mark:

```
█ ▀▀  Garrick · Work › Acme › Pricing active · 42%
█ ██  Wrap  Clear  Close  Finder  Obsidian
```

- The Garrick mark, a 4×2 tile of terminal cells drawn with half blocks, as tall as the two lines, so the terminal needs no image support.
- `Garrick · <Zone> › <Project> › <Thread>`, with the note's `status` in colour: green for active, yellow for parked, grey for done. Then how full the context window is, as a whole percentage: dimmed up to 60%, red above it, the point where it is time to wrap and clear. It is the status line's own figure, from the mods API's plain usage call, which costs nothing and counts no tokens, and it is read again after every turn. Before a session's first reply, from *Clear* or `/clear` until the new conversation's first reply, and just after a compaction, there is no figure yet, and the band shows none.
- A row of buttons, all at one weight. Click one, or press ctrl+x tab to reach the band and then its letter:
  - *Wrap* (`w`) and *Resume* (`r`) share one slot, which follows the record. *Wrap* asks the assistant to rewrite the Resume here block and add today's dated entry, the rules' "wrap X": it asks nothing and, in Claude Code, runs the wrap in the background so you can leave. *Resume* asks where the thread stands and what comes next, the rules' "open X". The band shows *Wrap* when a turn has begun since the last wrap of the thread finished, and *Resume* after a wrap has finished in this session's last turn, or in a session with no turn yet. A write to the Resume here block by any other route is no wrap and leaves *Wrap* on offer. A wrap that is running shows as *Wrapping…*, with no button, and cannot be started a second time. The band takes the lock itself when you press *Wrap*; a wrap that dies leaves *Wrapping…* showing for up to ten minutes, until its lock expires. A finished or parked thread has neither.
  - *Clear* (`c`) runs `/clear`, which starts a new conversation in the same folder. The band stays. `/resume` brings back the conversation you cleared.
  - *Close* (`q`) ends your work on the thread: it wraps the thread if it needs it, then closes the session where it runs. See [Close](#close).
  - *Finder* (`f`) shows the thread note in Finder, on a Mac.
  - *Obsidian* (`o`) opens the thread note in Obsidian. It is offered only when Obsidian is installed and the note sits in a vault, so a folder like `System/`, which is not a vault, gets no Obsidian.

  *Finder* and *Obsidian*, here and in the Resume here pane, follow Settings › Opening a thread on the [status page](../../docs/extras/status-page.md#settings): *Obsidian* only while *Open the note* (`note`) is switched on, *Finder* only while *Reveal in Finder* is. The band reads `launchers` in `System/garrick-settings.json` when the session starts and after every turn. With no `launchers` saved, or a file that does not read, both are offered as above.

  At a project whose hub has no Resume here block because each thread keeps its own, *Wrap* asks the assistant to wrap the thread this session worked on, and the hub too if its status changed. When the session touched no thread, it says so and stops. `/garrick resume` asks where each live thread stands, and `/garrick note` shows every live thread's block. Parked and done threads are left out.

  Where there is no thread note above the folder, such as `System/`, the workspace root or a wiki, there is nothing to resume, wrap or show, so the band offers *Clear*, *Close* and *Finder*, which shows the folder. In a wiki, *Obsidian* opens its `wiki/index.md`.

When the band is older than the workspace, a third, dim line says so: "This band is from <commit>; the workspace runs <commit>. Run `python3 update.py` from the newer Garrick, or see Updating." The band reads the `VERSION` file of the Garrick it runs from (two folders above the plugin) and the workspace's `System/garrick-version.json` when the session starts and after every turn, and compares their commits. It says nothing when they match, when a file does not read or names no commit (a clone's `VERSION` names none), or when the band's date is later than the workspace's. `python3 System/tools/check.py --version` and the status page report the same mismatch.

The update keeps the copy current when it can. When the band runs from a release download that sits outside the workspace (its `VERSION` names a commit and the folder is not a git clone), `python3 update.py --apply` lists a step for it: it downloads the release the workspace now runs from GitHub, checks the old copy against the release it names, moves the old copy beside itself with its commit in the name (it never deletes it), and puts the new one in its place, so the path in your settings stays the same. A copy whose files differ from its release, and a clone, are left as they are, and the report prints the command that updates them: `git -C <folder> pull`, or a download and a new path in `~/.claude/settings.json`.

The band does not repeat what the session already shows: no Resume here paragraph, and no echo of your last prompt or the step the assistant is on.

Outside any project it shows the mark and where you are, such as `System` or `Wikis › Meetings`. It reads the note again after every turn, so a wrap shows up straight away.

How the slot is decided, with no model: the band compares the time the last wrap of the thread finished with the time the session's last turn began. A running wrap is known from a lock file the wrap writes in `System/generated/` (`wrap-<note path>.lock`, from `System/tools/wrap_lock.py`) and removes when it ends; a lock older than ten minutes counts as gone. `wrap_lock.py end` writes the time the wrap finished beside the lock (`wrap-<note path>.done`), once the wrap's commit has succeeded, and *Close* reads the same record to know the session was wrapped. A wrap that failed or whose commit was refused runs `end --abandon`, which removes the lock and writes no record, so the band still offers *Wrap*. The note's own modification time is not used, so a job, a checkout or an ordinary edit cannot move the slot. If there is no record, the band offers *Wrap*, which the lock keeps single.

The `[-]` at the band's right end is Claude Code's own: it folds the band, and `[+]` or ctrl+x ctrl+a opens it again. `/garrick hide` takes the band away altogether, and `/garrick` brings it back. `/garrick` always shows the band and never toggles it, because a mod cannot tell whether Claude Code has the band folded. It also works while a turn runs. `/garrick wrap`, `/garrick close`, `/garrick finder` and `/garrick obsidian` do what the buttons do, and bring back a hidden band. With the launcher switched off in Settings, `/garrick obsidian` answers "Obsidian is switched off in Settings › Opening a thread." and opens nothing, and `/garrick finder` the same for Finder. Two more have no button:

- `/garrick resume` asks the assistant to read the Resume here block and say where the thread stands and what comes next, the rules' "Open X", as saying "open X" does. You get the answer in the conversation, where you can carry on from it.
- `/garrick note` shows the whole Resume here block of the thread note in a pane. It reads the file and sends nothing to the model. The pane draws it as a reply is drawn, with tables and emphasis, and wikilinks and file paths become links that a click opens. Its *Open in Obsidian* and *Reveal in Finder* show the whole note.

In the assistant's replies, a path in backticks becomes a link, so Cmd-click opens the file in its default app, or a folder in Finder:

- A span counts as a path when it has a `/` or a file extension, so `claude plugin test` stays plain. Code fences are left alone.
- Absolute and `~/` paths link when the file exists. Anything else is matched against an index of the workspace: a full path, a partial one (`Deliverables/x.xlsx`) or a bare file name. When two files match, the one under the session's folder wins; otherwise the span stays plain, so you never get a dead link.
- A file written in the turn is not in the index yet. The mod looks for it under the session's folder and under each folder above it, up to the workspace root and never higher, so a path written relative to the project or the zone links too. A path with `..` stays plain.
- The index is one `find` over the workspace when the session starts and after every turn. It skips `.git`, `.obsidian`, `node_modules`, `__pycache__` and `.trash`, and `find` doesn't follow symlinks, so a cloud folder linked into the workspace is never walked.
- Only the drawing changes. The stored reply keeps its plain text.

How it finds the note: from the folder the session started in (a `cd` the assistant runs in a command does not move it) it walks up to the workspace root, the first folder holding `System/rules.md`. The first folder on the way that holds a note with its own name, `<Folder>/<Folder>.md`, is the thread or project. To show the band it only reads files and the usage figure, and never calls a model. *Wrap*, *Close* (when it needs a wrap) and `/garrick resume` send a prompt in your name, only when you ask. It runs these processes: that `find`; `open` when you press *Finder* or *Obsidian*; `desk close --session <id> --yes` when you press *Close* in cmux.

## Close

*Close* (`q`), or `/garrick close`, is for the end of a day's work on a thread: one press instead of Wrap, waiting, and closing the session by hand.

1. **It wraps first, unless there is nothing to wrap.** A session counts as wrapped when its last turn rewrote the Resume here block (from *Wrap*, `/garrick wrap`, or a turn of your own that did) and no turn has run since. A session with no turn yet, a finished thread, and a folder with no thread note, such as `System/`, have nothing to wrap. Otherwise Close sends the *Wrap* prompt with one addition: the wrap runs in front and asks no question, since the session ends when the note is written, and it goes on only when that turn ends with the block rewritten. While a wrap is already running on the thread (the lock above), Close starts none and closes nothing; press it again once the wrap has landed. At a project kept in threads, it is the live threads' blocks that must change.
2. **It fails closed.** If the wrap ends with a question, an error or an interruption, or leaves the block as it was, the session stays open and a toast says why, as "Not closed: the wrap is waiting on you." Press Close again once it is answered. Close never cuts off a turn that is running: pressed during one, it says it will wait, and wraps when the turn ends. Pressing it again meanwhile does nothing. It acts a moment after the wrap turn has ended, never inside it.
3. **It closes the session where it runs.**

   | Where | What Close does |
   |---|---|
   | cmux | runs `desk close --session <this session> --yes`, so the [desk](../../docs/extras/cmux.md) closes the tab once it sees the session idle (it tries three times, two seconds apart, while the transcript catches up). The tab leaves tomorrow's restore, as with "close the Pricing tab". Needs the `desk` command on your PATH. If the desk refuses, the session stays open and the toast gives its reason. The band takes it to be in cmux when `CMUX_SURFACE_ID` is set, as cmux sets it in each tab |
   | Claude desktop app | wraps, then says "Wrapped. Archive this session from the sidebar." The mods API has no call that ends a session or archives it, so the band does neither |
   | a plain terminal | runs `/exit`; if Claude Code will not run it from a mod, "Wrapped. Type /exit to close this session." |

The conversation is never deleted: `/resume` brings it back, and in the desktop app so does the archive.

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
