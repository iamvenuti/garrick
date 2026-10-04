# Changelog

What changed in each release. Dates are when the release was tagged. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- Garrick's mark: a white Gr on blue, set like an element tile, with a small "ai" in the full version (`docs/assets/garrick-mark.svg`, and `garrick-mark-favicon.svg` for small sizes). The letters are outlines of ANRT's Baskervville, under the SIL Open Font Licence. It sits beside the README's title, on the deck's cover and the social card, and in the status page's tab and heading; the deck, the social card and the adoption ladder take its blue as their accent. Display type is Baskerville, the face the mark is drawn in, across the deck, the social card, the adoption ladder and the status page.
- The README opens with the wall at work, as a GIF, and the launch walkthrough, remade in Garrick's brand and playing in the page; then an adoption ladder of four levels, each linking to its guides, whose third level now includes the status page.
- The `interview` skill: "interview me" opens with questions one at a time, including whose confidences you hold and which must never meet, keeps a record in `System/interviews/`, then proposes parties, walls, projects, threads and open actions and sets up only what you accept. Offered as an optional first step of the first session.
- `extras/jobs/`, optional and outside core: an assistant on a schedule. One runner for Claude or Codex, picked by `GARRICK_HARNESS`, with tiers instead of model names; a wrapper with log, heartbeat, lock, watchdog, sign-in check and idle alarm; a ledger of every call with daily, hourly and cost caps; for Claude, a permission mode that lets a job use only the tools it names, and a deny profile, loaded with user and project settings only, that refuses the sending, sharing, deleting and web tools it names and any edit to `System/`, without which no call is made; and an example job, a "what's open" brief per zone, with a launchd plist.
- `extras/status/`, optional and outside core: a status page, *Garrick's Status*. One self-contained HTML file with every live thread by zone and how long since it moved, what the check finds, open actions, what is waiting in the inboxes, the newest entry in each wiki's log, and, with the jobs extra, a fourteen-day strip per job and the spend against its caps. It shows names, tags, dates, counts, check findings and the targets of links, not what a note says; written to `System/generated/status.html`; links open the files, or Obsidian with `--obsidian VAULT`; nothing from the network. With a launchd plist for a nightly rebuild.
- The status page draws a graph of the workspace: every note in the zones and the wikis and the links between them, each zone and wiki starting in its own region, `AGENTS.md` and `Todo.md` left out. It rings threads that have gone quiet and opens a panel on click with the note's links, buttons to open it or its project, and the phrases to say. Parked projects stay off it until *Show parked*. It reads the targets of a note's links and nothing else from its body; `--no-graph` leaves it out. Every card can be dragged to another place or hidden, *Needs attention* excepted, and *Reset view* puts the page back as built. The arrangement is kept in the browser. The graph fills its card, keeps names clear of each other, stays quick on a large workspace and draws mail in its own colour.
- On the status page, hovering a thread in the list, or reaching it with the keyboard, opens a card with the same actions as the graph's panel. The list is sorted by name, and each zone's open actions have a link to its `Todo.md`.
- Parking a thread: "park X" sets it aside with `status: parked`, out of "what's open", the end-of-day wrap, the scheduled brief and the Resume-links check, with its note untouched; "wake X" brings it back and "what's parked" lists them. The status page folds parked threads into their own group, and its buttons copy the phrase to say ("open Pricing", "park Pricing", "wake Pricing") or the rebuild command.
- Notes of a call pasted into the conversation are filed like a dropped transcript: saved unedited to the Meetings inbox, then ingested. Asked to, prep saves its brief as a dated deliverable, after the same wall check, and commits it through the hook.
- `scaffold.py zone "<Zone>" --holds "<what it holds>"` adds a zone after install, made as the installer makes one; "add a zone called X" runs it.
- The wall check holds more: wording from a meeting page still missing its parties, and from a walled project's own files; person pages, which carry a known party and nothing said in a meeting; Knowledge pages, where `party` is refused like `parties` and wording shared with a meeting is flagged; the Meetings inbox, now ignored and checked like a zone's; thread and project statuses and dates. It warns when `core.hooksPath` sends commits past the hook.
- The demo is a fuller month: 21 filed meetings, 15 people, 9 published sources, working notes, deliverables and received files, so the status page's graph has 94 notes and 217 links.
- `System/generated/`, for pages a tool rebuilds. The installer's root `.gitignore` names it, and `check.py` reports a generated file that is committed or a `.gitignore` without the line.
- `check.py` warns when a link or a file path in a live thread's Resume here block leads nowhere, so a deliverable renamed or moved shows up in the next check, not in the next cold resume.
- Questions and feedback go to the repository's Discussions, linked from the issue chooser, the README and `CONTRIBUTING.md`. A bug report takes a desktop app's version as well as the command-line ones.
- A sixteenth slide in the introduction, for the status page.
- Every workspace records which Garrick it was installed from, in `System/garrick-version.json`: the commit and its date, and whether it came as a download or a clone. `python3 System/tools/check.py --version` says it in one line, and the bug form asks for that line. A download from GitHub carries its commit in `VERSION`, which git fills in.
- A table of what has been tested in Claude Code and in Codex, each with the version it was checked on, in the harnesses guide.

### Changed

- The wall check counts wording as common only when it also appears in a file every side reads by design: the instruction files, `System/rules.md`, `System/context.md`, the skills, templates and tools, and the Knowledge wiki. An interview record, a generated page or anything else in `System/` no longer exempts what it repeats.
- The installer refuses a target that is, holds or sits inside the folder it runs from, comparing folders rather than names: on a Mac, `~/garrick` and `~/Garrick` are one folder. A folder typed at the question goes in the home folder, the confirmation shows the full path, git is checked before the first question, the end of input stops it cleanly, and its last line suits either route.
- The docs clone into `~/garrick-source`, and every example workspace has a folder of its own.
- The workspace's `AGENTS.md` tells the assistant to search `Zones/` and `Wikis/` by path: the root's `.gitignore` leaves them out, so search tools started at the root skip them.
- The threads skill's listing works the same in zsh and bash, and prints nothing on a workspace with no threads yet.
- Open actions have one line format, `<action> · <project>, <thread> · <date>`. "What do I owe them" reads the zone's `Todo.md`, and prep reads it too, within the walls.
- Spoken phrases: "wrap it" wraps; "unpark X" wakes a thread as "wake X" does; "pick X up again" is gone, too close to "pick up X".
- First steps for a newcomer: the Command Line Tools dialog, the Downloads permission, and which commands the first session asks to approve and how to allow them once.
- The cmux guide gives each assistant's own resume command, and a section on switching between Claude and Codex: both read the same notes and skills, while each keeps its own conversation history.
- The zone template lives in `template/System/templates/zone/`, so an installed workspace can make new zones. The installer offers only tags it accepts, treats aliases as something to add later, and uses invented tags in its wall example.
- Scheduled jobs take their lock before touching a log, skip cleanly when another run holds the shared lock, accept one plain word as a job's name, rotate the Codex transcript, keep sixty days of ledger, and leave launchd a log of its own.
- The diagram shows the desktop app as the main way to talk to the assistant, and says what the walls are: declared, with limited checks before a commit.
- Separate desktop and terminal onboarding routes, with a shared first session that files one conversation, produces a brief and verifies resuming from a fresh chat.
- Guided setup brings real use and a fictional wall demonstration into the first session. Obsidian, cmux, mail fetching and phone access are optional follow-ons.
- Clarify declared pairwise walls, supported checks and their limits. Lead with continuity of work and local ownership instead of an absolute confidentiality claim.
- Document Codex remote voice on iPhone with its desktop host requirement, and Claude Code Remote Control from a terminal.
- The Obsidian guide shows how to make the graph readable: colour notes by level, leave parked and finished threads out, and link notes rather than quoting their paths, since Obsidian draws no line from a path in backticks.
- The installer's `.gitignore` files leave out Obsidian's `workspace.json` and `graph.json` in any folder opened as a vault, since Obsidian rewrites both on every pan and zoom. Obsidian's settings are still tracked.
- A scheduled job that only reads runs read-only under Codex too: no file written, the user's own Codex configuration ignored, and connectors, plugins, the browser and web search switched off. Checked against Codex 0.160.0. A job allowed to write keeps the write sandbox and its connectors.
- First steps name the git commands a session asks to approve by what they do (`status`, `diff`, `log`, `add`, `commit`), say to read the whole line, and keep Claude's "don't ask again" off a rule that stops at the folder.
- The walls' stated limits add wording moved rather than copied: cut from one party's note, pasted into another's and committed together, it passes, since only the history says where it came from.

### Fixed

- The status page: its right column no longer renders right-aligned; the Wikis card reads the logs as they are written; the Wikis repository appears under Repositories; a note's title can no longer break the page's embedded data; the rebuild command it copies runs from anywhere; a mistyped `--workspace` stops instead of creating folders; and it reads frontmatter as `check.py` does. It also builds without git, opens a symlinked note in Obsidian, reads schedules from any plist, monthly ones included, gives one attention line per capped job, and says a project name shared by two zones with its zone.
- The deck no longer says deleting the folder leaves nothing behind: the assistant's own chat history stays.
- The demo builder takes a relative target as relative to where you run it.
- The commit check reads what it is not committing as git holds it as well as from disk: a source edited or deleted without staging, in the same zone or in another repository, still counts, and a shared file counts as common only for the wording both versions hold. A project or thread whose party differs between disk and the staged copy is refused.
- The commit check refuses files at any depth in a zone's `Inbox/` or the Meetings inbox, not only those directly inside.
- The "what's open" job reads a thread's status with the workspace's own parser, so `status: parked # until next quarter` and `status: "done"` keep a thread out of the brief.

## [0.1.0] - 2026-09-30

First public release.

### Added

- `install.py`: asks one question at a time, or reads a config file; writes nothing outside its target; links the skills for Claude Code and Codex.
- The workspace template: root rules and context, zones as separate git repositories, projects and threads with one "Resume here" point each, and two memories, Meetings and Knowledge.
- `scaffold.py` for new projects and threads, and `check.py`, which checks the workspace against its own rules.
- The wall check: a pre-commit hook in every zone that refuses a walled party's names, links, or eight-word runs of its meeting wording.
- Four skills: `threads`, `intake`, `meetings` and `knowledge`.
- Ways in: every zone has an `Inbox/` folder for mail and any other file. The `intake` skill sorts it by rules in `System/rules.md`: a conversation into Meetings, something to read into Knowledge, material for a project into its `Sources/`, with the mail it came in kept in Meetings. Its helper only lists, parses and moves; parties are suggested from a new Domains column in `System/context.md`, and asked about whenever the addresses do not settle them. `check.py` holds the walls on mail pages and on attachments saved to a project, keeps parties off Knowledge pages, and keeps inboxes out of history. Fetching is separate and optional: your assistant's mail connector, a mail rule, or the IMAP script in `extras/fetch/`, which takes its password from the macOS Keychain.
- `extras/fetch/imap_fetch.py`, optional and outside core: saves one IMAP mailbox or label into one zone's `Inbox/` with no assistant involved, so the assistant's vendor sees only the mail you file. The password comes from the macOS Keychain only. Works with password sign-in (Gmail app passwords, iCloud Mail, Fastmail), not with Microsoft 365 or Outlook.com, which accept only OAuth.
- A demo workspace built by `examples/demo/build.py`: an invented advisor, four weeks in.
- Documentation, the extras (tools that pair with Garrick but are not part of it), and a fifteen-slide introduction.

[Unreleased]: https://github.com/iamvenuti/garrick/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/iamvenuti/garrick/releases/tag/v0.1.0
