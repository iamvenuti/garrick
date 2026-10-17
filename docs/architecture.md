# Architecture

Garrick is a shell around Claude Code or Codex: you work through it, and the agent does the work underneath, in its desktop app or a terminal. This page names its parts and follows four flows through them, and the [overview diagram](architecture/overview.png) ([interactive version](architecture/overview.html)) draws the same parts.

The words in it are defined in [Concepts](concepts.md).

## The parts

### The workspace

**The workspace** is a folder of Markdown files under git, `~/Garrick` by default, made by the installer from the repository's `template/`. It has three kinds of place, each its own git repository or part of one:

- **Zones**, in `Zones/<Zone>/`, one repository each. A zone holds its **projects**, each project its **work threads**, and each thread one note with its Resume here block. The zone's `Todo.md` is its list of open actions, and its `Inbox/` is where mail and files wait to be sorted.
- **The two wikis**, in `Wikis/`, one repository between them. **Meetings** holds every conversation from every zone, each page with its zone and parties. **Knowledge** holds published material you read, with no parties. Each keeps the record as it arrived in `raw/` and its pages in `wiki/`.
- **`System/`**, in the workspace root's own repository: the rules, `context.md`, the skills, the tools and the templates. `System/generated/` holds pages a tool rebuilds, such as the status page, and is never committed.

The root's `.gitignore` leaves `Zones/` and `Wikis/` out, so each repository has one history and a commit never spans two of them.

### The rules

**The rules** are plain files the assistant reads before it does anything. They say what goes where and who never mixes:

- `AGENTS.md` at the root is the entry point. It sends the assistant to `System/rules.md` and `System/context.md`, and routes each question by its subject. Each zone, `Wikis/` and each wiki has its own `AGENTS.md`, which adds what holds only there.
- `System/rules.md` says how the assistant behaves: what it may do without asking, the walls, the ways in, threads, voice and files. It is Garrick's, as shipped.
- `System/context.md` says who you are and who you deal with: zones, parties, walls, people and aliases. It is yours.
- `System/rules.local.md`, and an `AGENTS.local.md` beside any `AGENTS.md`, hold your own rules and routing.

Where two say different things, the local file wins over the Garrick file beside it, and a zone's or a wiki's `AGENTS.md` wins over the root's where it says so. An update replaces Garrick's files and never touches yours. See [Garrick's rules, and yours](principles.md#garricks-rules-and-yours).

### The skills

**The skills** are the procedures, one `SKILL.md` each in `System/skills/`, linked into `.claude/skills` and `.agents/skills` so both assistants find them. The assistant picks one when a request matches it:

| Skill | What it does | Started by |
|---|---|---|
| `threads` | Opens, wraps, holds, parks, finishes, renames and creates threads, and adds zones | "open X", "wrap it", "close for the day", "I'm being interrupted", "back", "park X", "what's open", "new project X for Acme" |
| `intake` | Sorts the inboxes, one item at a time, by the Ways in rules | "process the inbox", "file my mail", "file this" |
| `meetings` | Files a conversation as a Meetings page, and briefs for a meeting | "file this transcript", "log this call", "prep me for X" |
| `knowledge` | Freezes published material into the Knowledge wiki, and answers from it | "read this", "add this to knowledge", "what does my library say about X" |
| `todo` | Sweeps actions the records hold into each zone's `Todo.md`, and tidies it | "sweep my actions", "what do I owe people", "what am I waiting on" |
| `interview` | Asks about your work one question at a time, then proposes parties, walls, projects and threads | "interview me", "help me set up my workspace" |
| `setup` | Finds out what your Mac has and how you work, and writes it down | "set up Garrick", "check my setup", "add a rule", "set up notifications" |
| `update` | Brings the workspace up to a newer Garrick, and merges what it leaves | "update Garrick", "merge the update", "split my rules" |

The cmux extra adds a ninth, `desk`, below.

### The tools

**The tools** are Python scripts, standard library only, for what code does better than an assistant. They move, parse, check and list; they never choose where a thing goes.

- `check.py` tests the workspace against every rule a machine can check. Run by hand it reports; run by the pre-commit hook as `--staged --walls-only` it refuses. See [The check](commands.md#the-check).
- `scaffold.py` makes zones, parties, projects and threads, and parks, wakes, renames and deletes them. It checks a name and a party before it writes anything. See [Your first project](commands.md#your-first-project).
- `garrick_lib.py` is what the other tools share: reading frontmatter and `context.md`, the naming and tag rules, and writing the wall hook into a repository.
- `operations.py` declares every action the status page can ask for, in one table, `DECLARED`, and keeps a durable record of six of them.
- `install.py`, in the repository and not in the workspace, makes a workspace. `install.py --update` runs `update.py` beside it, which brings a workspace up to that Garrick.
- `release.py` asks GitHub whether a newer Garrick is out and runs the update from it, only when asked or switched on.
- `notifications.py` is the one way Garrick tells you something: every notice goes through it, to this Mac, cmux, Telegram or a command of your own, as the status page's Settings › Notifications says. It installs the hooks that let a Claude Code or Codex session say it needs you or has finished. With `release.py`, it is one of the two tools that reach the network, and only to the Telegram chat you switch on.
- `probe.py` lists what the Mac has, for the setup skill; `drift.py` compares a published deliverable with its shared copy; `wiki_lint.py` finds orphan pages and broken links in a wiki.

### The guards

**The guards** are the code that stops something rather than reporting it:

- **The pre-commit wall check.** The installer writes a git hook into each zone that runs `check.py --staged --walls-only` on what is being committed. A project file that links to, names or quotes a party across a declared wall is refused with one line naming the file and the wall, and so is anything from an inbox. `check.py --install-hooks` puts the hook back, and the check warns when git's `core.hooksPath` setting sends commits past it.
- **The zone guard**, optional. A hook for Claude Code and Codex that stops the assistant once before it edits a file outside the project the session was opened in, so that it asks you. It covers the file-editing tools, not shell commands, and records nothing about your answer. See [the zone guard](../extras/hooks/README.md).

[What is enforced, and what is asked](enforced.md) lists every guard beside the rules that depend on the assistant alone.

### The assistant

**Your assistant** is Claude Code or Codex, in its desktop app or a terminal. Garrick has no model and no app of its own: the assistant reads the files, follows the rules and the skills, runs the tools and writes the notes. Garrick asks it to read `AGENTS.md` and the rules before anything else, to ask before anything leaves the machine or cannot be undone, to check the Walls table before it uses a meeting, and never to skip the wall check with `git commit --no-verify`. The assistant's own permissions decide what it can run; the installer can allow Garrick's own tools and git's read and save commands, and nothing that pushes. See [Assistant compatibility](harnesses.md).

### The extras

**The extras** are optional, in the repository's `extras/`. `install.py` installs none of them, and the workspace works without all of them. See [Extras](extras/index.md).

- **The status page** builds one HTML page, shown in a browser, the Garrick Mac app or Obsidian. Its overview opens on the live threads, each with its next action or a *no next action* chip, by name or most recently touched first; the graph of every note sits behind *Explore*. A thread is marked by its own next action, a due date passed or a chase date come, or by a check finding in its folder, never by its age. See [the status page](extras/status-page.md), and [its actions](#the-status-pages-actions) below.
- **Obsidian** browses the workspace as a linked vault. See [Obsidian](extras/obsidian.md).
- **cmux**, with its `desk` skill, gives each thread a terminal tab of its own, opened and closed by voice or from the status page. See [cmux](extras/cmux.md).
- **Phone access** reaches the workspace through the assistants' own remote features. See [Phone access](extras/phone-access.md).
- **Scheduled jobs** run the check, a script or an assistant on a schedule, under a deny profile and spend caps. See [Scheduled jobs](extras/scheduled-jobs.md).
- **Ways in** fetch mail into a zone's inbox without doing it by hand, and a **meeting recorder** feeds the Meetings inbox. See [Ways in](extras/ways-in.md) and [A meeting recorder](extras/meeting-recorder.md).
- **The Garrick band** is a Claude Code mod that shows the current thread and its resume point above the prompt. See [the Garrick band](../extras/mods/README.md).
- **The zone guard** is above, under the guards.

#### The status page's actions

Every action the page can ask for, from its buttons, its Ask box or a skill, goes through `page_action.py` in the status extra, and every one is declared in one table, `DECLARED` in `System/tools/operations.py`. A row per verb names the fields a request may carry, which of them say what the request is, what it may touch, whether it commits, whether a retry is safe, and what must still be true for it to run. Validation is closed: a request that carries a field its verb does not declare is refused, and the field is named. Park, wake and the four Todo verbs, the subset `OPS`, also keep a durable record in `operations.jsonl` in the jobs folder, so a reloaded page can find an action still running or learn how it ended, and so the same request sent again is recognised: joined or answered inside a double click's window, and past it, for as long as any client could still be waiting, asked about rather than done twice. That folder is outside the workspace, so the record is never committed; the notes and git stay the record of what changed. A launcher, such as *Open in Claude*, is reported the same honest way: the page says only that it is opening, and the Mac app or the Obsidian plugin, which alone knows how it went, says what opened. A Mac app built before that change says nothing back, so the opening line is all there is until it is rebuilt.

## The flows

### Material coming in

**Recordings**, **mail** and **files you drop in** arrive by one of the [ways in](extras/ways-in.md): by hand, by a script or by your assistant's mail connector. Each lands in an inbox first: a transcript in `Wikis/Meetings/raw/inbox/`, mail and other files in a zone's `Inbox/`. "Process the inbox" starts the `intake` skill, which looks at each item and **files it where it belongs** by the Ways in rules. A recording is always a conversation, filed in Meetings. A mail exchange is filed in Meetings too, with its zone and parties; something to read goes to Knowledge; material for a project goes into its `Sources/`, after the wall between the project's party and the material's parties is checked. When the zone, a party or the project is unclear, the assistant asks.

### A working day

You open a session in your app or terminal and say "open Acme pricing". The assistant reads the thread's Resume here block and answers in two sentences: where it stands, and the next action. You work, and what the session writes is committed in the zone's repository, where the wall check runs on every commit. If something cuts in, "I'm being interrupted" saves your place in the block and puts the thread on the interruption stack, and "back" brings it back. At the end, "wrap it" rewrites the Resume here block so it describes now, adds a dated entry below it, puts open actions in the zone's `Todo.md` and commits. "Close for the day" does that for every thread touched today. The next session, in either assistant, starts from that block.

### The walls

Walls are declared in one place, the Walls table of `System/context.md`, and every project and meeting carries the party tags they are checked against. They are read by the assistant: before it uses a meeting in a project, the rules ask it to compare the project's party with the meeting's parties and leave walled material out, saying only that something was held back. They are enforced, in part, by code: the pre-commit hook in each zone refuses a project file that links to a walled meeting, names a party or person from across the wall, or repeats eight words held only on the far side. A clean paraphrase, a chat reply and anything sent are outside what the hook can see, and the check has known gaps. See [What the check covers](principles.md#what-the-check-covers) and [What is enforced, and what is asked](enforced.md).

### An update

Garrick publishes a release. "Update Garrick", or `python3 System/tools/release.py update`, downloads it into a temporary folder outside the workspace and runs that release's own `install.py --update`, which compares every file it would write with yours and with the fingerprint recorded when Garrick last wrote it. It reports first: a file you never changed is replaced, a new one is added, and a file you changed that Garrick changed too gets Garrick's version beside it as a `.new`. Your rules, your `context.md`, your notes and the local files are never replaced. With `--apply` it writes the files and makes one commit in each repository it touched, which `git revert` undoes. "Merge the update" then goes through each `.new` with you, and the check warns while one waits. See [Updating](updating.md).
