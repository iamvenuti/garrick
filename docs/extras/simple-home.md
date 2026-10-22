# The simple home

The [status page](status-page.md) can open on a simpler page: your work, a box to ask something, and the questions Garrick is waiting on you for. It is for someone who does not want to think in zones, projects and threads, or work in a terminal. Everything else the status page has is still there, under *More*.

A workspace installed with this Garrick opens on the simple home. One installed earlier keeps the page it had. *Settings › Home* switches between the two, *Simple* and *Full*, for every viewer of the page: the choice is `"home": "simple"` or `"full"` in `System/garrick-settings.json`, committed with the rest of your settings. On the simple home each zone's `Todo.md` starts empty, without the example line a list on the full home opens with to show its shape; a zone added later follows the setting the workspace has then.

## What it shows

- **Ask something.** One box. Type a question about any of your work, or something new you want to start, and press *Ask*. Claude's desktop app opens on your words, already answered: see [Continue](#continue).
- **Needs you.** The questions Garrick has asked and is waiting on, each blocking a piece of work, each answered in one click. Empty, it says *Nothing needs you*. See [Needs you](#needs-you).
- **Your work.** Every live piece of work, most recent first: five, and the rest under *more*. Each row shows its next action, when it last moved and what you owe other people, such as *2 owed, 1 due Thursday*. A row whose next step is yours has a **Continue** button. A row waiting on someone says so instead, *Waiting on Theo Marsh*, with no button. A piece of work's name opens its page.

The words *Work* and *piece of work* are the only unit the home shows. Underneath, a piece of work is a project with one thread. A project with several live threads shows one row for each, as *Project, Thread*.

A row is read from what Garrick keeps already. The next action and who it waits on come from the thread's `### Resume here` block, its *Next action* and *Waiting on* rows; *Waiting on* that says anyone other than nobody makes the row a waiting one. When it last moved is the note's `updated:` date, or a later unwrapped checkpoint. What is owed is the zone's `Todo.md` lines that open with the thread's link: each unticked line is one owed, a `📅` date makes it due, and a `#waiting` line, which someone owes you, is not counted.

Unlike the full page, the simple home shows some of a note's words: its *Where it stands* line, *Next action* and *Waiting on*, its newest dated entry and its opening sentence. A piece of work means nothing without them. The page itself still lives in `System/generated/`, never committed and left out of the wall check, as the full page always has.

At the top right sit a dot, *More* and the cog for Settings. The dot is green when nothing on the Status tab needs attention, and says how many things do when something does: a failed job, a check finding, an update. Clicking it opens the Status tab. *More* opens the Overview, with the Todo, Status and Guide tabs beside it and *Home* first among them. The graph, the diagnostics, the ways to open a thread and every setting are where they always were.

## A piece of work's page

Click a piece of work's name. Its page says what it is (the note's opening sentence), who is involved (its party in `System/context.md` and the people listed for it), what happened last (its newest dated entry), what is open (a question waiting on you, the Todo lines it owes, who it waits on) and the next step, with **Continue in Claude**.

Below that are its files, newest first. By default they are the project's own: `Sources/`, `Deliverables/` and anything else in the project's folder, leaving out Garrick's notes. A project whose hub names a folder, `folder: Shared drive/Harbour Lease` in its frontmatter, from the workspace's root, absolute, or from `~/`, lists that folder's files instead. Each file says whether it is *new* or *changed* since you last pressed Continue on the work, and a file that has gone since then is listed as *missing*. Before the first Continue, a file is *new* if it changed after the work last moved. *‹ Home* goes back.

## Continue

Continue opens Claude's desktop app on the piece of work, with Claude's answer to where it stands already on screen. The app's own ask box has no tools, so the conversation happens in Claude. The way in is the Claude Code command-line tool's `claude --desktop`, which opens the desktop app on a folder or, with `--resume <session id>`, on one session. It takes no prompt, so Continue, through `page_action.py`:

1. commits Garrick's own record of the work, so the desktop app's *Changes* panel has nothing of Garrick's to offer you: the work's note, its project's hub and its questions in *Needs you*, by name. Anything else in the folder is yours and is left as it is, committed or not;
2. asks Claude, without a window, in the work's folder: `claude -p "Where am I on Acme Review?" --output-format json --name "Acme Review" --append-system-prompt "<how to answer>" --disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit`. Claude reads the workspace's `AGENTS.md` and answers, and the answer carries a session id. Since that answer is the first thing you see, the appended instruction asks for two or three plain sentences: where the work stands and the next step, with who it waits on and a deadline if one is near. It asks for no table, no file paths or links and no commands, and for nothing about tools or checks the call does not have, nor about Garrick's record of the work: no Resume here block or its rows, no placeholder, and nothing about how a file was read; a checkpoint not yet confirmed may come up once, as not yet saved. That call only reads: whatever the workspace allows, it runs no command and writes no file before you see anything. The session it hands over keeps the workspace's own permissions, and is named after the work, by the name the home shows;
3. opens that session with `claude --desktop --resume <id>`, in a terminal of its own that nobody sees, since `--desktop` refuses to run without one.

The question names the work as the threads skill says it, by the shortest name that is unique: "Where am I on Interviews?" for one of several threads while no other thread has that name, the project and the thread where one does, and the project's name for a project that is one thread. *Open in Claude* on a thread, on the full home's cards, in its graph and in the app's menu and panel, sends this same request, so both homes open work in Claude one way and share its session.

You land on the question and Claude's answer, with the box ready for your next message. A second Continue within twelve hours opens the same session again without asking; after that it asks afresh, so Claude reads where the work stands now. The session ids, and the files as they stood at each Continue, are kept on this Mac in `System/generated/desktop-sessions.json`, never committed.

The work's folder is Garrick's own record of it: the project's folder for a project that is one thread, the thread's folder for one of several. That folder's name is what the desktop app's sidebar shows.

Continue needs the Claude Code command-line tool installed and signed in with the same Claude account as the desktop app. It looks for the tool where Anthropic's installer puts it, `~/.local/bin/claude`, then in the usual places and on the path. It skips a shell script standing in front of the tool, such as one a terminal app adds to pass `--settings`, which `--desktop` refuses. `GARRICK_CLAUDE` names the tool outright. Without it, Continue says it is not installed and what to do.

**Ask something** works the same way, in the workspace's own folder, so Claude sees every piece of work, with your words in place of *Where am I on…*, and the session named after their first few words, up to 40 characters. Its instruction asks for the same plain words, with no paths, commands or talk of tools, but at whatever length your question needs.

## Your own work

*Add your own work*, beside *Your work*'s heading, points Garrick at a folder you already keep, such as a cloud drive, and starts on one piece of work in it. Garrick never changes anything in that folder, and Claude is set not to edit it; see *Read-only for Claude* below for what that does and does not cover.

1. **Pick the folder.** In the Garrick app the button opens the Mac's own folder picker, on your cloud drives where you have any; picking a folder also grants the app access to it. Garrick never looks anywhere you did not pick, and refuses the whole Mac, your home folder and its own folders. A browser cannot open the picker, so there the button copies what to ask Claude instead; in Obsidian it says to ask Claude.
2. **Garrick suggests the pieces of work in it.** `System/tools/discover.py` reads names, folders and dates only, never a file's contents, so a cloud drive's online-only files are not downloaded. The page shows three to five, most recently active first, each with where it is, when it last moved and how many files it has, and the rest under *more*. A line under them says what was left out and why: archives, templates, chat exports, a weekly report made again and again. A folder that is mostly loose files is offered as groups of names that share a word. The suggestions, and your answers to them, are kept on this Mac in `System/generated/discovery.json`, never committed; one you have not answered is still there next time, and *See them* on the home goes back to it.
3. **Answer each one.** *Yes* makes Garrick's record of the work: a project with one thread, named after it, whose hub's `folder:` points at the folder, committed by name in its zone and nothing else with it. *Rename* is a yes under a name you type. *Not a piece of work* is remembered, so it is never suggested again. The work joins your workspace's only place for work; where there are several, one line above the suggestions asks which. Where that place has no one's work in it yet, as in a workspace nobody has been interviewed in, one more line asks *Whose work is this?*: your employer's name, or *my own*. Garrick adds that as a party in `System/context.md`, through `scaffold.py party`, commits it on its own in the workspace's repository, and goes on with your *Yes* or *Rename* in the same click. A name you typed for a rename is kept if anything refuses it, so you never type it twice. A workspace with nowhere to keep work at all says to ask Claude to set it up. Nothing is merged or split.
4. **Start with this one.** What you said yes to waits on the home under *Start with one*. Only now are that work's files read. `System/tools/extract.py` takes the text out of its Word, PowerPoint and Excel files into `System/generated/extracts/`, never committed and remade only when a file changes. Then one call to Claude, without a window and read-only, reads the folder and the extracts and answers with a first look: what the work is, who is involved, what happened last, what is open, the next step and where it comes from. Garrick writes that into the thread's Resume here block, the hub's opening sentence and a dated entry, and asks the next step as a Needs you question, *That's right* or *Change it*, all in one commit through the zone's wall check. The work's page marks the first look as made just now, to be checked.
5. **The suggested request.** Once you answer, the work's page shows one request drawn from the next step, and *Continue in Claude* opens Claude's desktop app with that request already asked. *Change it* takes the next step in your words, and the request follows them. After that, Continue asks where the work stands, as for any other piece of work, and the next day it picks up from there with nothing retold.

**Read-only for Claude.** Every call on such a piece of work gets the folder with `--add-dir`, and the text of its Office files beside it; the instruction Continue gives Claude with its question, and with a suggested request, says where that text is, so the session reads it there instead of opening the files. The question you see as yours carries no path. A deny rule, `Edit(//<the folder>/**)`, keeps Claude's file-editing tools out of the folder: Claude Code's Edit rule covers every tool that edits or writes a file. Claude Code reads a project's settings only from the folder a session starts in, never from one above it, so Garrick puts the rule in that folder's `.claude/settings.json`: for a piece of work that is one thread, the project's own folder in the zone. It is written when you say yes, before anything reads the folder, keeps whatever else the file holds, and is committed with the project, so it moves with it when the work is put away and brought back; Continue puts it back if it was taken out. Every call Garrick makes without a window also carries the same rule with `--settings`. The rule stops Claude's editing tools in every permission mode, Auto included. What it does not cover is a shell command. Garrick's own calls run none, but a session in the desktop app may: in Auto mode it runs commands such as `cd`, `file` or `unzip` without asking, and in the other modes it asks first. A command that changes a file in the folder, approved by you or run by Auto mode, is not stopped. Garrick adds no rules for shell commands.

**Stop using this**, at the foot of the work's page, puts Garrick's record of it away: its project moves into the zone's `archive/` folder, marked with the day, in one commit. Its folder of files is left exactly as it was. *Bring it back*, at the foot of the home, returns the record where it stood.

## Where these files live

A piece of work from a folder of yours says at the foot of its page where its files live: *left in place*, at first, where Garrick only reads them. **Change** opens three choices for that piece of work only, the one in use marked *Now*. Each opens to a preview of what it does, what it costs in space and download, and who else it touches, with the real sizes of the work's files, and one button that carries it out. Nothing is chosen during setup, and your other work stays as it is.

- **Leave in place.** Garrick reads the folder and never changes it. This is what every piece of work starts as.
- **Keep a copy.** Garrick copies the work's files into its project's `Files/` folder and refreshes the copy one way from your folder, which stays the original: you and anyone else keep working there, and nobody edits Garrick's copy. Each refresh keeps a version of what changed, so the copy holds the history of the files, even in a shared folder. It refreshes when you press *Continue in Claude* on the work, before Claude opens, and from **Refresh now**; nothing runs in the background. Recordings and video stay out by default, while photos, PDFs and documents go in; a switch brings them in, after saying how much it downloads and that each version of them takes that space again. Claude still reads your folder, read-only as before, so it sees the latest; the copy is for its history.
- **Move into Garrick.** Every file is copied into the work's `Files/` folder and checked against its original, and only when every one matches is any removed from your folder. The preview says plainly that anyone else using the folder will no longer see the files, and that a link to one of them stops working: Garrick reads only names and dates, so it cannot tell who else has access, and names the people the work involves instead. Nothing is written into the folder, not even a note, and the emptied folder is kept, so *Undo the move* has somewhere to put the files back. The files then open from the work's page, each in its own app, and **Show them in Finder** opens that piece of work's `Files/` folder and nothing above it. Claude reads them there, and may change them like any file of the work.

While a copy or a move runs, the page shows how far it has got, and **Stop** until files start leaving the folder: stopping leaves your folder and the workspace as they were, and deletes what Garrick had copied.

**Versions.** A copy, and moved files, keep a small history of their own: a git repository in the `Files/` folder, marked as Garrick's, which the project's `.gitignore` keeps out of the zone's history, so a large Office file never grows the zone's history, an unchanged file takes no extra space, and deleting the copy deletes all of it. The workspace's checks and their hooks leave it alone. A file with earlier versions says how many beside its name. Each version can be **opened** to read, from a file of its own, or saved with **Save a copy** as a separate file wherever you choose, named like *Launch brief, 3 days ago*: the Garrick app opens the Mac's Save panel, and elsewhere it goes into Downloads. A version is never put back over a file, and never saved into your folder or into Garrick's copy. Moved files get a version each time you press Continue, before Claude opens, so a change Claude makes can be undone by saving the version from before it.

**Going back.** From a copy, *Leave in place* keeps the copy, no longer refreshed, or deletes it with every version; an old copy can still be deleted later. From a move, *Undo the move* comes first: every file goes back into your folder as it is now in Garrick, each checked there. A file of the same name already in the folder is never replaced: Garrick's goes back beside it as "*name* (from Garrick)", and the undo says which. Garrick keeps its copy, with its versions, until you delete it. *Stop using this* on moved work puts the files back first, as Undo does, then puts Garrick's record away with its copy, so *Bring it back* returns both. Nothing is deleted.

**What Claude may change.** The rule that keeps Claude's editing tools out of your folder stays whichever you choose. While the files are left in place or copied, a second rule keeps them out of Garrick's copy too; once the files are moved in, that rule comes off, and the session on the work gets the moved files with `--add-dir`. The rules are in the `.claude/settings.json` of the work's project, committed with Garrick's record of where the files live: the hub's `storage: copy` or `storage: moved`, `media: in` for the media switch and `moved:` with the day. What this Mac keeps of the last refresh, and of a copy or a move as it runs, is in `System/generated/`, never committed. A project with a copy or moved files cannot be renamed or deleted from the page, since the zone's history could not bring its `Files/` folder back: delete the copy, or undo the move, first.

## When Claude cannot open work on this Mac

An organisation can turn off the desktop app's sessions on your own computer, with a managed setting, `disableDesktopLocalSessions`, that its Mac management pushes. Continue checks for it first, in `/Library/Managed Preferences/`, and also notices when the desktop app refuses for that reason. Either way the home says so, in plain words:

> **Claude can't open work on this Mac.** Your company has turned off Claude's local sessions. Garrick still keeps where each piece of work stands, and Ask something still answers. Your IT team can turn local sessions back on for you.

Nothing else changes. Your work and where it stands are all still there, and *Ask something* still answers: Claude's answer comes back to the home, under the box, since it cannot open in the app. The note goes once a Continue opens again.

## Needs you

A question Garrick asks you is a file, so it survives a restart and is committed with its zone like any note. It sits in the folder of the work it blocks: `Threads/<Thread>/Needs you/<YYMMDD> - <slug>.md`, or the project's own `Needs you/` for a project with no thread notes. The session that raises the question writes it:

```markdown
---
type: question
asked: 2026-10-15
status: open
---

**Acme Review: which volume floor did you agree with Dana?**

In the call on Tuesday Dana said 400 pallets and you said 500. The price sheet waits on this.

- [400 pallets] Send Dana the price sheet at a 400-pallet floor
- [500 pallets] Send Dana the price sheet at a 500-pallet floor
```

The bold line is the question. The lines under it say why it matters. Each option is `- [<label>] <the next action it leads to>`, and the home shows one button per option, plus *Not now*.

- **An answer** sets the work's *Next action* to what that option leads to, ends its *Where it stands* with one sentence, *Answered on 17 October 2026: 500 pallets.*, leaving the rest of what you wrote there as it is, adds a dated entry, *Answered: 500 pallets.*, writes `status: answered`, `answer:` and `answered:` into the question, and commits the note and the question together in the zone, through its wall check.
- **Not now** writes `status: later` and `later:` with tomorrow's date, and commits it. The question leaves the home, which counts it as *1 put off*, and comes back on that day.
- **A question with no options** is answered in words, in Claude: its button is *Answer in Claude*, which is Continue.

Technical warnings, updates and check findings never go here. They go to the dot by Settings. `check.py` warns about a question file the home would leave out: one with no `type: question`, a status other than `open`, `answered` or `later`, a `later` with no date, an answer with no `answer:`, or no bold line to ask.

## The example

When a workspace has the example zone, `Example`, its pieces of work are marked *Example* and a line at the foot says they are made up. *Remove the example* puts it away through `System/tools/example.py archive`, and *Bring the example back*, there once it is away, puts it back through `example.py restore`. Nothing of yours is touched either way. With no work at all, the home says how to start: ask for what you are working on in Ask something.

## What the actions are

The buttons on the home act through `page_action.py`, as every button on the status page does, and are listed with the rest under [What the actions keep](status-page.md#what-the-actions-keep): `answer`, `later`, `continue`, `ask-desktop`, `example`, `discover`, `suggestion`, `start`, `stop-using`, `bring-back`, `files`, `files-stop`, `files-progress`, `work-file`, and `settings` with `home`. In a browser, where the page cannot act, *Continue* and *Ask* copy what to say to Claude instead.
