# Extra: the Garrick band, a Claude Code mod

A session opened in a thread folder doesn't know where it is until the assistant has read the thread note. That takes a turn, and the answer scrolls away. When the assistant names a file in a reply, the path is plain text, so you go to Finder and look for it. `garrick-band` fixes both in Claude Code without spending a token.

It is Claude Code only, and optional. Core Garrick never depends on it. It displays what your notes already say and enforces nothing, so a Codex session misses only the display.

## What it shows

Above the prompt:

- The Garrick mark, a 6×3 tile of terminal cells drawn with half blocks, so the terminal needs no image support.
- `Garrick · <Zone> › <Project> › <Thread>`, with the note's `status` in colour: green for active, yellow for parked, grey for done.
- The first paragraph of the thread's `### Resume here` block, cut to one line. On a finished thread it shows `### Outcome` instead.
- *Resume here*, which opens the whole block in a pane, and *Hide*.

Outside any project it shows the mark and where you are, such as `System` or `Wikis › Meetings`. It reads the note again after every turn, so a wrap shows up straight away.

`/garrick` shows or hides the band, and `/garrick resume` opens the pane.

In the assistant's replies, a path in backticks becomes a link, so Cmd-click opens the file in its default app, or a folder in Finder:

- A span counts as a path when it has a `/` or a file extension, so `claude plugin test` stays plain. Code fences are left alone.
- Absolute and `~/` paths link when the file exists. Anything else is matched against an index of the workspace: a full path, a partial one (`Deliverables/x.xlsx`) or a bare file name. When two files match, the one under the session's folder wins; otherwise the span stays plain, so you never get a dead link.
- The index is one `find` over the workspace when the session starts and after every turn. It skips `.git`, `.obsidian`, `node_modules`, `__pycache__` and `.trash`, and `find` doesn't follow symlinks, so a cloud folder linked into the workspace is never walked.
- Only the drawing changes. The stored reply keeps its plain text.

How it finds the note: from the session's folder it walks up to the workspace root, the first folder holding `System/rules.md`. The first folder on the way that holds a note with its own name, `<Folder>/<Folder>.md`, is the thread or project. It only reads files and never calls a model. The one process it runs is that `find`.

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

Point it at the folder of the Garrick download you keep. When you update Garrick, the next session loads the new copy. To stop loading it, remove the line.

## Check it

From `extras/mods/`:

```sh
claude plugin validate garrick-band
claude plugin test garrick-band
```

The repository's test suite runs both when `claude` is installed, and CI runs them on the tested version.
