# Extra: the Garrick band, a Claude Code mod

A session opened in a thread folder doesn't know where it is until the assistant has read the thread note. That takes a turn, and the answer scrolls away. When the assistant names a file in a reply, the path is plain text, so you go to Finder and look for it. `garrick-band` fixes both in Claude Code, and spends no tokens until you press one of its buttons.

It is Claude Code only, and optional. Core Garrick never depends on it. It displays what your notes already say and enforces nothing, so a Codex session misses only the display.

## What it shows

Above the prompt:

- The Garrick mark, a 6×3 tile of terminal cells drawn with half blocks, so the terminal needs no image support.
- `Garrick · <Zone> › <Project> › <Thread>`, with the note's `status` in colour: green for active, yellow for parked, grey for done.
- One line under it. When the session opens, it shows the first paragraph of the thread's `### Resume here` block (`### Outcome` on a finished thread). Once you send a prompt, it shows that prompt's first line instead. While the assistant works, the step it is on follows it: `Editing register.tsx`, `Run the tests`, `Searching for TODO`. It describes your prompt and the tools the assistant calls, and a subagent's calls are left out. Nothing is summarised by a model. `/clear` brings back the Resume line.
- A row of actions. Click one, or press ctrl+x tab to reach the band and then its letter:
  - *Resume* (`r`) asks the assistant to read the Resume here block and say where the thread stands and what comes next, the rules' "Open X". You get the answer in the conversation, where you can carry on from it.
  - *Wrap* (`w`) asks it to rewrite the Resume here block and add today's dated entry, the rules' "wrap X". A finished thread has no Wrap.
  - *Clear* (`c`) runs `/clear`, which starts a new conversation in the same folder. The band stays, so *Resume* is one click away. `/resume` brings back the conversation you cleared.
  - *Note* (`n`) shows the whole Resume here block of the thread note in a pane. It reads the file and sends nothing to the model. The pane draws it as a reply is drawn, with tables and emphasis, and wikilinks and file paths become links that a click opens. Its *Open in Obsidian* and *Reveal in Finder* show the whole note.
  - *Finder* (`f`) shows the thread note in Finder, on a Mac.
  - *Obsidian* (`o`) opens the thread note in Obsidian. It is offered only when Obsidian is installed and the note sits in a vault, so a folder like `System/`, which is not a vault, gets no Obsidian.

  Where there is no thread note above the folder, such as `System/`, the workspace root or a wiki, there is nothing to resume, wrap or show, so the band offers *Clear* and *Finder*, which shows the folder. In a wiki, *Obsidian* opens its `wiki/index.md`.

Outside any project it shows the mark and where you are, such as `System` or `Wikis › Meetings`. It reads the note again after every turn, so a wrap shows up straight away.

The `[-]` at the band's right end is Claude Code's own: it folds the band, and `[+]` or ctrl+x ctrl+a opens it again. `/garrick hide` takes the band away altogether, and `/garrick` brings it back. `/garrick` always shows the band and never toggles it, because a mod cannot tell whether Claude Code has the band folded. It also works while a turn runs. `/garrick resume`, `/garrick wrap`, `/garrick note`, `/garrick finder` and `/garrick obsidian` do what the buttons do, and bring back a hidden band.

In the assistant's replies, a path in backticks becomes a link, so Cmd-click opens the file in its default app, or a folder in Finder:

- A span counts as a path when it has a `/` or a file extension, so `claude plugin test` stays plain. Code fences are left alone.
- Absolute and `~/` paths link when the file exists. Anything else is matched against an index of the workspace: a full path, a partial one (`Deliverables/x.xlsx`) or a bare file name. When two files match, the one under the session's folder wins; otherwise the span stays plain, so you never get a dead link.
- The index is one `find` over the workspace when the session starts and after every turn. It skips `.git`, `.obsidian`, `node_modules`, `__pycache__` and `.trash`, and `find` doesn't follow symlinks, so a cloud folder linked into the workspace is never walked.
- Only the drawing changes. The stored reply keeps its plain text.

How it finds the note: from the folder the session started in (a `cd` the assistant runs in a command does not move it) it walks up to the workspace root, the first folder holding `System/rules.md`. The first folder on the way that holds a note with its own name, `<Folder>/<Folder>.md`, is the thread or project. To show the band it only reads files and never calls a model. *Resume* and *Wrap* send a prompt in your name, only when you press them. It runs two processes: that `find`, and `open` when you press *Finder* or *Obsidian*.

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
