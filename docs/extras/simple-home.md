# The simple home

The [status page](status-page.md) can open on a simpler page: your work, a box to ask something, and the questions Garrick is waiting on you for. It is for someone who does not want to think in zones, projects and threads, or work in a terminal. Everything else the status page has is still there, under *More*.

A workspace installed with this Garrick opens on the simple home. One installed earlier keeps the page it had. *Settings › Home* switches between the two, *Simple* and *Full*, for every viewer of the page: the choice is `"home": "simple"` or `"full"` in `System/garrick-settings.json`, committed with the rest of your settings.

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
2. asks Claude, without a window, in the work's folder: `claude -p "Where am I on Acme Review?" --output-format json --disallowedTools=Bash,Edit,Write,MultiEdit,NotebookEdit`. Claude reads the workspace's `AGENTS.md` and answers, and the answer carries a session id. That call only reads: whatever the workspace allows, it runs no command and writes no file before you see anything. The session it hands over keeps the workspace's own permissions;
3. opens that session with `claude --desktop --resume <id>`, in a terminal of its own that nobody sees, since `--desktop` refuses to run without one.

You land on the question and Claude's answer, with the box ready for your next message. A second Continue within twelve hours opens the same session again without asking; after that it asks afresh, so Claude reads where the work stands now. The session ids, and the files as they stood at each Continue, are kept on this Mac in `System/generated/desktop-sessions.json`, never committed.

The work's folder is Garrick's own record of it: the project's folder for a project that is one thread, the thread's folder for one of several. That folder's name is what the desktop app's sidebar shows.

Continue needs the Claude Code command-line tool installed and signed in with the same Claude account as the desktop app. It looks for the tool where Anthropic's installer puts it, `~/.local/bin/claude`, then in the usual places and on the path. It skips a shell script standing in front of the tool, such as one a terminal app adds to pass `--settings`, which `--desktop` refuses. `GARRICK_CLAUDE` names the tool outright. Without it, Continue says it is not installed and what to do.

**Ask something** works the same way, in the workspace's own folder, so Claude sees every piece of work, with your words in place of *Where am I on…*.

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

- **An answer** sets the work's *Next action* to what that option leads to, adds a dated entry, *Answered: 500 pallets.*, writes `status: answered`, `answer:` and `answered:` into the question, and commits the note and the question together in the zone, through its wall check.
- **Not now** writes `status: later` and `later:` with tomorrow's date, and commits it. The question leaves the home, which counts it as *1 put off*, and comes back on that day.
- **A question with no options** is answered in words, in Claude: its button is *Answer in Claude*, which is Continue.

Technical warnings, updates and check findings never go here. They go to the dot by Settings. `check.py` warns about a question file the home would leave out: one with no `type: question`, a status other than `open`, `answered` or `later`, a `later` with no date, an answer with no `answer:`, or no bold line to ask.

## The example

When a workspace has the example zone, `Example`, its pieces of work are marked *Example* and a line at the foot says they are made up. *Remove the example* puts it away through `System/tools/example.py archive`, and *Bring the example back*, there once it is away, puts it back through `example.py restore`. Nothing of yours is touched either way. With no work at all, the home says how to start: ask for what you are working on in Ask something.

## What the actions are

The buttons on the home act through `page_action.py`, as every button on the status page does, and are listed with the rest under [What the actions keep](status-page.md#what-the-actions-keep): `answer`, `later`, `continue`, `ask-desktop`, `example`, and `settings` with `home`. In a browser, where the page cannot act, *Continue* and *Ask* copy what to say to Claude instead.
