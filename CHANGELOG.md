# Changelog

What changed in each release. Dates are when the release was tagged. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- A lint for the Meetings and Knowledge wikis, on request ("lint the wikis"). `System/tools/wiki_lint.py` lists what a script can find, pages that link nowhere and that nothing links to, and links to pages that are not there. The *Lint* section of the `meetings` and `knowledge` skills then reads for contradictions between pages, stale claims, claims only their vendor makes and names with no page of their own, and writes a dated report in the wiki's `wiki/lint/`. Nothing else changes: the user picks what to fix. ([#49](https://github.com/iamvenuti/garrick/issues/49))
- One call that covers several projects can become a page per project. The `meetings` skill proposes the split when a transcript plainly runs through more than one existing project, and writes it only when the user agrees. Each page keeps the same `raw:` link, names every other in a new `split-with:` field, carries only its own section's parties and says which part of the record it covers; its actions are routed as for any page. `check.py` reports pages that share a raw record without naming each other, and a mail filed as a split is read with each page's own parties. ([#13](https://github.com/iamvenuti/garrick/issues/13))
- Projects and threads can be made, renamed and deleted from the status page and by voice. `scaffold.py` gains `--check` (every refusal, nothing made), `rename` (the folder and note move with git, and every link in the zone follows: the hub's list, `Todo.md`, `project:` frontmatter, the notes between; one commit; the old name becomes a heard alias), `delete` (lists what would go until the name is typed again, then removes the folder, the hub's line and the open `Todo.md` lines naming it in one commit) and `undo`, which reverts either while it is the zone's last commit. The `threads` skill gains *Rename* and *Delete*. The Threads card gains *New project* and *New thread*, and each card *Rename…*, *Delete…* and, on a project, *New thread here*: in the app with `page-actions` on they act through six new `page_action.py` verbs, and elsewhere they copy the phrase. The menu bar's and panel's *New thread…*, and checking a name as it is typed, wait for a change to the app. ([#36](https://github.com/iamvenuti/garrick/issues/36), [#37](https://github.com/iamvenuti/garrick/issues/37), [#38](https://github.com/iamvenuti/garrick/issues/38))
- A recording or mail filed twice no longer gets two pages. `ingest.py land` and `intake.py file-conversation` refuse a transcript or mail whose bytes, or whose ID (an `.eml`'s Message-ID, or `source-id`, `message-id` or `recording-id` in a transcript's frontmatter), match a record already in `Wikis/Meetings/raw/`, at any depth, and name that record. A mail page records its Message-ID as `source-id:`. ([#52](https://github.com/iamvenuti/garrick/issues/52))
- The wall check reaches a git repository inside a project, such as a product's code or a site, which the zone's own hook never saw and which is the one most likely to be pushed somewhere public. `check.py --install-hooks` installs the hook there too, checking staged files on the project's side of the walls, and `check.py` warns about such a repository that has a remote and no hook. ([#43](https://github.com/iamvenuti/garrick/issues/43))
- A backup job in the jobs extra, `backup.py`, with a launchd example that runs it at 12:30 and 23:30. It commits and pushes every repository of the workspace, holding back only the files the wall check refuses, so one walled note no longer stops a zone from being backed up; one notice names what it held. It never forces, rebases or merges: a remote that moved ahead is reported, and offline it commits and waits. Exit 5 (held back) and 6 (offline) are quiet; offline for more than three days is a failure. ([#44](https://github.com/iamvenuti/garrick/issues/44))
- An action filed from a meeting keeps its way back to the conversation when the zone and the wikis are separate Obsidian vaults. `ingest.py link` prints the source the `meetings` skill writes on the line: `[[<slug>]]` when one vault holds both, an `obsidian://open` link into the wikis' vault when each is its own. ([#48](https://github.com/iamvenuti/garrick/issues/48))

### Changed

- The Resume here block has a sixth row, *Keep in mind*: what only you know, such as a decision half made and which way you leaned, or a doubt about a figure. `nothing` is a valid answer. The next action must be small enough to start in two minutes. The `threads` skill's wrap asks for both and "open X" reads *Keep in mind* back, the `setup` skill's *Fill in my resume points* asks the new question, and `check.py` reports the row while it still holds the template's prompt. A block written before the row existed stays valid. ([#31](https://github.com/iamvenuti/garrick/issues/31))
- "Open X" on a parked thread wakes it, as "wake X" does, and says so in a few words before where it stands; before, it asked first, so every session the status page opened on a parked thread stopped on that question. A thread parked with its project wakes the project. Questions that only look at a thread leave it parked. ([#16](https://github.com/iamvenuti/garrick/issues/16))
- `ingest.py index` rewrote the whole of the Meetings `index.md`, so a table or notes kept there by hand were lost on the next ingest. It now writes only the page table, between `<!-- garrick:index -->` and `<!-- /garrick:index -->`, and keeps the rest. On an index from before the markers it replaces its own Page, Type, Updated table, or adds the block at the end. ([#51](https://github.com/iamvenuti/garrick/issues/51))

### Fixed

- `release.py update` stopped with `CERTIFICATE_VERIFY_FAILED` under python.org's Python on macOS, which has no certificates until *Install Certificates.command* is run, and said nothing about why. It now fetches through `curl`, which trusts the system's certificates, and says so; when that fails too, it says to run `/usr/bin/python3` or *Install Certificates.command*. The update docs say the same. ([#55](https://github.com/iamvenuti/garrick/issues/55))
- `ingest.py log` added its line at the bottom of a log without Garrick's "One line per ingest" line, in a log that reads newest first. With no such line, it now goes after the title and any text under it, above the first entry or section. ([#53](https://github.com/iamvenuti/garrick/issues/53))
- `check.py` warned that an instruction file "lists skills" once it and its local file named three skills anywhere, even in separate sentences that each point at one procedure. A list is now three or more skill names in one block: one bullet list, one table or one paragraph. ([#47](https://github.com/iamvenuti/garrick/issues/47))
- `check.py` stayed silent when a section of `context.md` was there but not a table it could read: People written as prose left every name unchecked across the walls, and Parties, Walls, Aliases and Zones did as little. A section with text and no table is now an error that names the columns to write, and a table without a column the checks need is a warning. ([#42](https://github.com/iamvenuti/garrick/issues/42))
- The wall check compared project files with a meeting's transcript only when the transcript sat directly in `Wikis/Meetings/raw/`; one in a subfolder was never read, so copying it word for word went unnoticed. A page's `raw:` (or `transcript:`) link is now followed to any depth under `raw/`, and the slug is looked for there too; `raw/inbox/` is still not a record. Saved mails in subfolders are matched the same way. ([#41](https://github.com/iamvenuti/garrick/issues/41))
- `intake.py file-reading` froze a mail saved as Markdown or text into Knowledge with every recipient address still in it: the frontmatter's `to:` and `delivered-to:`, each `To:` line, and your address in a forward's `From:`. Such a mail now loses its recipient keys and lines, and each recipient address and each of your own (from `context.md`) becomes `you@removed.invalid`, in an `.eml` too. A mail that still names who received it is refused instead of filed. ([#30](https://github.com/iamvenuti/garrick/issues/30))
- desk refused to shut down, end or close over a Claude Code tab with no prompt since it was launched or cleared with `/clear`, saying it could not tell whether the tab was idle: Claude Code writes no transcript until the first prompt. Such a tab now reads `empty` when Claude Code's own session record shows it idle. It is closed without a wrap, `close --wrap` refuses it with "nothing to wrap", and it is left out of the restore list. ([#54](https://github.com/iamvenuti/garrick/issues/54))
- The graph's legend named a colour group by its raw query, so a folder group showed its whole path and a quoted property its brackets and quotes. A group is now named as a person would say it: a folder by its last name (`domains/system-integrator` reads *System integrator*), a file by its name, a property by its value, a word said once even as singular and plural, and *Group 2* for one with no term Garrick reads. A property term with its key or value in quotes now matches by property too. ([#39](https://github.com/iamvenuti/garrick/issues/39))
- A cmux tab that *Process the Inbox* or *Ask Garrick* opened at the workspace root was named after the folder, *Garrick* on a default install, so two such tabs could not be told apart and "close the X tab" had no X. *Process the Inbox* now opens a tab called *Inbox*, a question gets its first few words, and `desk open` at the root without `--title` names the tab *Workspace*. ([#33](https://github.com/iamvenuti/garrick/issues/33))

## [0.16.1] - 2026-10-11

The split keeps code blocks whole, its own header no longer reads as copied text, and each .gitignore gets a block Garrick manages, so your own lines outside it never come back as a .new.

### Fixed

- An update offered a `.gitignore` as a `.new` to merge once you had added a line of your own, since it cannot have a local file beside it. Each `.gitignore` Garrick writes now keeps Garrick's lines between two markers, and yours go anywhere outside them. An update replaces only the lines between the markers, and gives a `.gitignore` without them the markers at the top, with every line of yours kept after them. `check.py` warns when the lines between the markers differ from Garrick's.
- The split broke a fenced code block of yours apart when you had changed a line inside it: your line went to the review section and the rest of the block stayed behind, leaving the local file with a fence that never closed. A code block is now one passage. It moves whole, and one you changed is settled whole, fences included.
- `check.py` warned that the local files the split starts say the same thing, over the line each one opens with. That line is Garrick's, and the copy check now passes over it.

## [0.16.0] - 2026-10-11

Garrick's instruction files stay as it ships them: your own rules and routing live beside them in local files, and an update moves what you had changed there, asking about what it cannot place. Process the Inbox opens even when cmux remembers a session it cannot read, and the Mac app's answers reach you with its window out of sight.

### Added

- Your own rules and routing live in a local file beside each of Garrick's instruction files: `System/rules.local.md` beside `System/rules.md`, and `AGENTS.local.md` beside any `AGENTS.md`. Garrick never ships, lists or changes them. Each of Garrick's files tells the assistant to read its local file next, and the local file wins where the two differ. The installer starts `System/rules.local.md` with a heading and no rules.
- `install.py --update --split`, and `release.py update --split`, move your own text out of an instruction file of Garrick's into the local file beside it and put Garrick's back as shipped. It finds the Garrick version your file grew from in its history, moves what you added under the same heading, and lists each passage where you changed or removed Garrick's text, for you to settle one at a time; those wait in the local file under *From your earlier rules.md, to review*. Report first, `--apply` to write, nothing of yours lost.
- The `setup` skill writes a rule of your own into `System/rules.local.md` when you say "add a rule", and the `interview` skill proposes the ones it hears.
- `check.py` warns when one of Garrick's instruction files differs from what Garrick shipped, when a local file is not pointed to by the file beside it, and while a split leaves passages to settle. Each `AGENTS.local.md` has the word budget of its `AGENTS.md`, and the copy and skill-list checks read a Garrick file and its local file together.

### Changed

- An update replaces `System/rules.md` and every `AGENTS.md` like the rest of Garrick's files, when you have not changed them. One you changed is listed under *Split* and left as it is, with no `.new` beside it.

### Fixed

- *Process the Inbox* did nothing when cmux still remembered a session at the workspace root that desk could not read, as an old session in a reused tab: desk refused to type into it and said so where nobody saw it. desk now passes over a tab it cannot read and starts a new one on the prompt; a tab that is mid-turn is still left alone.
- The Mac app's answer to a button, a menu row or Ask showed only in its window. With the window out of sight it now comes as a notification as well.

## [0.15.5] - 2026-10-11

With the cmux extra, every way of opening a tab starts its session: Process the Inbox, Ask and the menu's rows as well as the cards. Cards lose the project's note button.

### Changed

- With the cmux extra's desk ready (the extra, cmux and the preview `page-actions`), everything Garrick.app opens in cmux goes through desk, so the new tab starts the assistant rather than waiting at a prompt with the phrase on the clipboard. That now covers *Process the Inbox* in the menu and the panel, a tab at the workspace root that starts on "process the inbox"; the words typed in the menu's or panel's field with the preview `ask` off, at the root too; Ask's opens in cmux; and the menu's and panel's rows, all through one rule in the app's `launch`. The page's menu data says `dk` when the desk is ready, and Ask marks its opens the same way. The Obsidian plugin follows the same rule. Without the desk, cmux opens the folder with the phrase on the clipboard, as before.
- `page_action.py`'s `open` also takes `{"folder", "prompt"}`: the workspace root, whose tab starts on the prompt, or a project's or thread's folder, opened as by name. Any other folder, a prompt that starts with `-`, and an empty or overlong one are refused. The log names the folder and cuts the prompt to 60 characters.
- A thread's card no longer has a button with its project's name that opens the project's note, in the threads list or the graph's panel. *Open* opens the thread; the project's note opens from the project's own row and card.

## [0.15.4] - 2026-10-11

The threads list and its cards say less and line up, Park and Wake show at once, the Mac app opens without a flicker, and it writes down what its menu holds, for a bug no one could reproduce.

### Added

- Garrick.app writes `garrick-app-menu.json` in the jobs folder each time it fills its menu or its panel: what it had to fill them with, in counts and zone names, the rows it built, and when the page last told it what to list. It is there for a menu that lists less than the page holds. `--check` also prints the page's script errors.

### Changed

- *Park* and *Wake* on a card show at once: when the app or the Obsidian plugin says the change was made, the row moves to the zone's *Parked* fold or back, its card follows and the counts with it, greyed until the rebuild confirms it. A rebuild asked for while one runs now follows it instead of being dropped.
- Party tags are on a thread's card only, no longer under its name in the threads list.
- A card in the threads list no longer opens with the line naming its kind, zone and project: the column says the zone, and a thread's project button says the project. The graph's panel keeps the line.
- The menu's script runs in a script element of its own, so an error elsewhere on the page cannot keep the app's menu from hearing what to list.

### Fixed

- A project that is its own thread had a project button on its card that opened the same note as *Open*. It shows only for a thread in a project of several.
- In the threads list, a live session's dot touched the name before it. It now sits a small gap after it.
- A launch of Garrick.app from the Finder or the Dock showed its Dock icon, took it away and brought it back before the window. The app now starts as a regular app and goes straight to its window; only a login launch with the window left closed turns into a menu bar app, out of sight.

## [0.15.3] - 2026-10-11

Garrick can tell you when a newer release is out, if you switch that on, and an update now brings the status page, the jobs and desk along with the rest. The Mac app opens at the first try, its panel lines up, the Ask hotkey is yours to set, and a whole project can be parked.

### Added

- A release notice, off until you switch it on with `{"release-notice": true}` in `System/garrick-settings.json`; the `setup` skill offers it once. Then the status page asks GitHub at most once a day, in the background, whether a newer Garrick is out, and *Needs attention* says "Garrick 0.16.0 is out; this workspace runs 0.15.2", with the command that updates and a link to the release notes. `check.py --version` adds the same line, read from the last answer and never asking itself. It is Garrick's first call out on its own: one GET to GitHub's latest-release address with a User-Agent naming Garrick and the release, and nothing about the workspace. A failed request shows nothing.
- `System/tools/release.py`: `latest` says whether a newer Garrick is out, and `update` downloads the newest release, or the one `--tag` names, into a temporary folder outside the workspace and runs its update from there, a report first and the changes with `--apply`. It refuses a release older than the workspace runs.
- The update keeps the extras a workspace has copied in up to date with the rest: the status page in `System/status`, the scheduled jobs in `System/jobs`, and desk in `System/cmux` with its skill in `System/skills/desk`. Their files are fingerprinted in the version stamp, replaced where you have not changed them and given a `.new` where you have, and `--only` picks among them as among the core's.
- After the files, the update does what an extra needs next, listed in the report first: it rebuilds Garrick.app with the flags it was built with, refreshes the Obsidian plugin in every vault inside the workspace that has it, and points a `desk` link to another copy at the workspace's. It names a zone guard or Garrick band run from a copy that differs from the newer Garrick's.
- Settings › Menu bar › *Ask hotkey*: the key that opens the Ask box from any app (preview `ask`), recorded like the menu's *Hotkey*, ⌘G until you set another, and clearable. *File › Ask Garrick…* shows it. One key never serves both fields; a *Hotkey* of ⌘G takes it from an *Ask hotkey* you never set.
- *Park* and *Wake* for a whole project, on its card in the threads list and in the graph's panel: the hub says `status: parked`, with a dated entry under its `## State of play` if it has one, and every thread in it is parked with it until the project wakes. `page_action.py` takes `{"verb": "park", "zone", "project"}`, Ask proposes it when you name a project, and the threads skill parks a project the same way.

### Changed

- desk installs into the workspace, as `System/cmux/`, beside the status page, so the page's tab buttons find it and the update keeps it current; the `desk` command links to that copy.
- `release-hashes.json` records the extras' files too, where a workspace keeps them, so a file copied in by hand from any release counts as Garrick's.
- The `update` skill runs `release.py update` and names the release it reported when it applies; a Garrick you downloaded yourself still works as before.
- A thread card's *Open project* is now the project's name with a note's icon, and says in its tooltip that it opens the project's note.

### Fixed

- The Mac app's panel put a session's dot before a name, so names with a session open no longer lined up with the rest. The dot now follows the name.
- In the threads list, a project with no thread notes, which has no chevron, started its name a chevron's width to the left of the others. Every project's name now starts in one column.
- The Mac app's hotkey fields could not record a key the app itself held, ⌘G above all with the preview `ask` on: the app's own shortcut took the key before the field saw it. The app now lets go of its shortcuts while a field records. A shortcut with only ⌥ or ⌥⇧, which macOS 15 and later never pass to an app, is refused in the field with that reason, and one macOS will not register is said as such instead of *Another app already uses that shortcut*.
- Opening the Mac app showed nothing when its window had been closed with the menu in the menu bar or a panel: only a second launch brought the window. Now a launch you make shows the window, and only a launch at login starts with it out of sight.

## [0.15.2] - 2026-10-10

The Mac app's menu bar menu finds and asks as the panel does, ⌘G asks from any app, the panel opens folded and remembers, and a job that has not run yet still shows on the page.

### Added

- The Mac app's menu bar menu has a field at its top, as the panel has: typing finds a project or thread, Return opens the first found, and with nothing found it asks, through the Ask box with the preview `ask` on or your assistant with it off.
- `job.py --detach` starts the run in a session of its own and returns at once, for a hook that starts a job and should neither wait for it nor take it down when it ends.
- With the preview `ask` on, ⌘G opens the Ask box from any app, not only with Garrick's window in front. A hotkey you set to ⌘G yourself keeps opening the menu or the panel.

### Changed

- The panel's projects start folded, and the panel remembers which ones you unfolded, after a restart too.
- The panel shows trouble as the red dot on its mark, as the menu bar does, with a tooltip that says what it means, instead of the words *Something failed*.
- The hotkey set in Settings opens the menu, with the cursor in its field, whatever the preview `ask`; it no longer opens the Ask box instead.
- Project and thread cards in the Mac app and in Obsidian no longer show *Copy "open X"* beside the buttons that open them. A browser, where copying is the only action, keeps it, and so does a card no app is offered for.

### Fixed

- The status page's *Scheduled jobs* card lists a job whose plist runs `job.py` but which has not run yet, with its schedule and *not run yet*, in a neutral row. It listed only jobs with a heartbeat, so a new job was invisible until its first run.
- `job.py` leaves alone a stop signal that was ignored when it started. Under `nohup`, as a session hook starts a job, the end of the hook sent SIGHUP and stopped the run; it now runs on and writes its own end line and heartbeat.
- Asking from the menu bar icon: its menu had no way to ask, and the Ask box opened only from the window or the hotkey. It now runs `ask.py` exactly as the panel does.

## [0.15.1] - 2026-10-10

The status page builds in seconds again on a large workspace.

### Changed

- The status page runs `check.py --quick` as it builds, leaving out the comparison of wording with the meetings, so a build after a button takes seconds rather than most of a minute on a large workspace. The commit hook still compares wording, and a full `check.py` on a schedule covers the rest.

## [0.15.0] - 2026-10-10

The status page, its Mac app and its actions do much more: the full Todo list, scheduled jobs that say when they are running, idle or quietly fine, a cost chart, an Obsidian tab with working buttons, one cmux tab per thread through the new `desk`, and an *Ask* preview that acts on what you type. Scheduled jobs tell you through a command of yours, `check.py` reads far more of the rules, and a year may stand in a name.

### Added

- Scheduled jobs tell you where you choose: `GARRICK_NOTIFY_CMD` runs a command of yours with a title and a message, beside or instead of the macOS notification of `GARRICK_NOTIFY=1`. See [Being told](docs/extras/scheduled-jobs.md#being-told).
- A failing job notifies on its first failure and on any change of exit code, then at most hourly while the failure lasts (`GARRICK_ALERT_REPEAT`), and always once when it works again. The notice and the log say why in words: could not sign in, a connector missing, a spending cap, timed out, or the exit code and how long it ran.
- `GARRICK_QUIET_EXITS`: exit codes, such as a partial sweep's, that are logged and marked `quiet` in the heartbeat and the log line, never notify, and count as a working run.
- `job.py status` prints every job's state as JSON: whether a run holds its lock now, its last heartbeat, and whether it is failing or idle. The heartbeat adds `started`, `finished_ts`, `ok`, `quiet`, `reason`, `idle`, `agent` and `failing_since`; the lock records when it was taken. See [What the status page reads](docs/extras/scheduled-jobs.md#what-the-status-page-reads).
- `job.py notify <title> <message>` sends a job's own line, such as a digest, through the same notifier.
- `GARRICK_ENV_FILE`: settings read into a run from a file, such as a sign-in token on a Mac nobody logs in to. The log names them and never shows their values.
- `agent.py run --prompt` takes the prompt itself, and `--timeout` stops one call with exit 124 so a job keeps time for its own steps. `agent.py items <n>` and `agent.py items-from <file>` report a count from the shell, the second from an `ITEMS <n>` line in the assistant's answer.
- The assistant-call ledger names the model each call used.
- The cmux extra, `extras/cmux/`: the `desk` skill and command keep one cmux tab per thread, for Claude Code and Codex alike. "Open Pricing" opens the thread's tab, or brings it forward, and its session starts on "open Pricing". "Close Pricing" has that session wrap the thread, then closes the tab. "Close for the day" wraps each tab used today in its own session, runs the commands you list under `before_quit`, then quits cmux; "shut everything down" quits without wrapping; "start the day" brings the tabs back and resumes any that came back empty. Nothing is closed or quit under a session that is mid-turn. Settings in `System/desk.json`, all optional. See [cmux](docs/extras/cmux.md).
- `cmuxlib.sessions_by_folder()` in the cmux extra: which folders have a live session, and whether it is idle or working, read from cmux's records and each session's transcript, for the status page.
- Four status page actions in `extras/status/page_action.py`, available when the cmux extra sits beside it and cmux is installed: `open` and `close` a project's or thread's tab, `startup` and `shutdown`. `close` is refused while a session there is mid-turn; `shutdown` checks first and then goes on in the background.
- An Obsidian plugin for the status page, in `extras/status/obsidian/`. It shows the page in an Obsidian tab with the buttons the Mac app gives it: Copy, *Rebuild now*, Finder, cmux, Codex and Claude, and the preview `page-actions` through `page_action.py`. It finds the workspace at or above the vault, or as named in its settings, and hides parked projects and threads in the file explorer. See [In Obsidian](docs/extras/status-page.md#in-obsidian).
- The preview `ask`: the status app's panel field, and a box ⌘G opens, answer a request in plain words ("open Pricing in Claude", "park the launch video", "what's open") and act on it. `ask.py` keeps a warm assistant session on `GARRICK_HARNESS` and `GARRICK_ASK_TIER`, under the scheduled jobs' deny profile and caps. It sees only names and states, and what it proposes is checked and run through `page_action.py`. Off, the field opens your assistant, as before. See [Ask](docs/extras/status-page.md#ask).
- `page-actions.log` in the jobs folder: one line for every request the page's buttons make, done or refused, naming only the fields its verb reads.
- A `settings` request to `page_action.py`, which saves *Opening a thread* to `System/generated/status-settings.json`, so every viewer of the page can share it.
- Edit › Cut, Paste, Undo and Redo in the status app, so ⌘V works in the Todo list's *Add* field and the panel's field. Safari's Web Inspector can open the app's page.
- The status page's Todo tab (preview `todo-list`) is the full list: one zone at a time, grouped under `Todo.md`'s headings, then *In thread notes* and *Done today*; *All*, *Overdue* and *No date* filters; *A–Z* or *Due date* sorting; counts of the open, overdue and undated. With `page-actions` in the app, a ticked line reopens, the date menu offers Friday, Next Monday and In two weeks as well as any date, and a line being added shows greyed until the rebuild.
- Thread rows say *no resume block* when a live thread's note has no `### Resume here` block, and a thread's card gives the date the block gives itself.
- The page shows a scheduled job as *running now* while its lock is held; raises an idle job (`idle` in its heartbeat, or `GARRICK_IDLE_DAYS`) and a repository with a change left uncommitted for over a day under *Needs attention*; and treats quiet exits (`ok` or `quiet` in the heartbeat, `GARRICK_QUIET_EXITS` in the plist, `quiet` on the log line) as fine, saying a failure's own `reason`.
- *Assistant calls* gains a fourteen-day cost chart, average turns per call, the per-call budget (`GARRICK_MAX_CALL_USD`), and refused tools checked against the deny list in `headless-settings.json`: a forbidden tool, a missing deny list or a call stopped at its budget goes under *Needs attention*.
- The graph takes a zone's or wiki's colours and excluded files from its own Obsidian vault (`.obsidian/graph.json`, `.obsidian/app.json`) when it has them. Every note in a project offers the apps its card does.
- With the cmux extra installed, a dot on rows, cards and menu rows says a session is open (green waiting, blue working). With cmux and `page-actions` too, *Open in cmux* goes through the desk, cards offer *Close session*, and the top row *Start up* and *Shut down*.
- `status.py --settle SECONDS` builds only after a burst of requests has stopped. After *Park*, *Wake*, *Open in cmux* or *Close session*, the page asks for rebuilds until it shows the change.
- `status.py --also FOLDER` and `--moved OLD=NEW`, passed to `effort.py`.
- Launcher settings saved for every viewer, in `System/generated/status-settings.json`: inside the app the page prefers them, and closing Settings after a change sends them to `page_action.py` to save.
- The check reads more of the rules: a missing `AGENTS.md` at the root or in a wiki; a zone's hand-kept list of projects that no longer matches the folder; two parties with one name and no wall between them; no Aliases table; a skill an assistant cannot find from the root, a zone or a wiki, through the repository's link or your own; a skill pinned to a model version, or copied in with no source commit; a hub that does not link a thread, or lists a finished one outside `## Finished`; a hub or thread note renamed `-v2`; a thread naming an unknown party; a meeting page naming both sides of a wall; a page in the Meetings wiki written for one party, a person or an organisation in one of its roles, that cites a meeting across a wall; a link from one zone into another; the full path of a cloud-synced folder in a note; a link to a page name both wikis hold that does not say which.
- Checks on to-do lists: an action whose thread link leads nowhere, a date with text after it, an Inbox that grew by more than twenty in a week.
- A resume point left behind is reported: files added to a project more than two weeks after its resume point was last updated. A hub's own Resume here block is read like a thread's, and a project that is only ever one thread may keep its resume point in its hub.
- Hub keys the check reads: `layout: thread-first`, for a project that keeps everything inside its threads; `anonymous: true`, or a list of names, for a project whose deliverables name nobody, Word, Excel and PowerPoint files included; `share:`, for a project whose files also live on a shared drive.
- `System/garrick-checks.json`, optional, for rules only some workspaces keep: `parent:` links on every note, notes linked rather than named as code, a thread link on every action, word budgets, retired skills, accepted changes to raw records, and which of Garrick's files are never changed here. See [check settings](docs/getting-started.md#check-settings).
- A project about the workspace itself can live in `System/<Project>/`, in no zone, and is checked like any other.
- `check.py --quick`: every check but the comparison of wording with the meetings, the slow part on a large workspace.
- The check warns when one of Garrick's own tools in `System/tools/` was changed here, or the version stamp does not read.
- `job.py check-scripts <file>...` reads job scripts, or the plists that run them, for a line that runs `claude -p` or `codex exec` itself instead of going through `agent.py`, and exits 1 when it finds one.
- A job run with `--agent` that exits 0 having added no line to the ledger says so in its log and with `no_call` in its heartbeat: either it had nothing to ask, or it reaches the assistant around `agent.py`, where no cap or deny profile holds it.
- `zone_guard.py --check` says whether the zone guard is registered for Claude Code and Codex, on every event and editing tool, from a script that exists, and changes nothing. It exits 1 when an assistant found lacks it. See [the zone guard](extras/hooks/README.md#check-it).
- The status page's actions doc lists every verb `page_action.py` takes, and a test fails when the two differ, so a new verb is reviewed before it ships.

### Changed

- A year standing as a word of its own is now part of a speakable name: "Harbour Summit 2027" is said "twenty twenty-seven", so a recurring event can carry its year. Any other digit is still refused, by the scaffold and by `check.py`, and `System/rules.md` says so.
- The idle notice repeats every `GARRICK_IDLE_DAYS` days while a job stays idle, rather than on every run, and `GARRICK_IDLE_DAYS=0` turns the alarm off. `GARRICK_NOTIFY=1` follows the same throttle: a lasting failure no longer raises a notification on every run.
- A Claude call stopped by its own budget, `GARRICK_MAX_CALL_USD`, exits 8 like a spending cap.
- `agent.py` refuses a Claude call, with exit 64 and nothing called, when its deny profile has lost an entry in `CORE_DENY`: sending, replying to and forwarding mail, binning mail and Drive files, making and deleting calendar events, sharing a Drive file, editing or commenting on a Notion page, and `curl`, `git push` and `rm`. A test holds the shipped profile to the same set.
- The deny profile for unattended Claude calls adds publishing Claude documents, the remaining Notion writes, starting or messaging other agent sessions, and the browser and computer-use servers.
- `System/rules.md` says what "open X", "close X" and "close for the day" do where the desk skill is installed, and the `threads` skill hands those phrases to it.
- Deliverables are checked in each thread's `Deliverables/` and in `archive/` too. Build intermediates (`build/`, `render/`, `specs/`), scripts, a `README.md` and a folder of build output are not deliverables, and an undated folder of dated deliverables is read inside.
- The name check on walled files is faster: plain ASCII text skips the accent folding, and each file's words are read once for every party.
- The status page raises a deny profile that has lost one of its core entries, as agent.py refuses it, and says when a scheduled run called no assistant, without raising it.

### Fixed

- A sign-in check that does not answer within 90 seconds, as when the Mac sleeps in the middle of it, no longer stops an assistant job: only a definite "not signed in" does.
- A job's lock whose process has gone, as after a crash, is taken over at the next run instead of blocking it for up to an hour.
- A second click on a Todo row before the page rebuilt was refused: a date changes a line's key, and the row still carried the old one. `page_action.py` now follows a line it re-dated in the last hour, so a second date, a tick or an undo lands on it.
- *Run now* said a job was running when its last run still held the lock, and the new run only skipped. It now says the job is already running.
- `check.py` no longer reads a git repository of its own inside a project, such as code checked out beside the notes about it, as the zone's files: its templates are not an unfinished install and its wording crosses no wall.
- A placeholder a note quotes as code, inline or in a fenced block, is no longer reported as unfilled.
- A folder named `archive` in a zone, in any case, is no longer taken for a project, so the walls no longer refuse a commit of retired to-do lines for having no party to check their meeting links against (#23).
- An HTML page is compared by the text a reader sees: its styles, scripts, comments, tags and attributes no longer count as wording, so two pages built from one slide template are no longer reported as repeating each other (#24).
- The text of a link to a shared file, such as a Knowledge page's title, no longer counts as wording, so two notes that list the same Knowledge pages are no longer reported across a wall (#25).
- `check.py` no longer reads any `node_modules`, `.venv`, `__pycache__` or `dist` folder, and the walls, sources and placeholder checks skip what the workspace's repositories ignore: an installed package's README no longer names a walled party. The inbox checks still read the inboxes, which are ignored by design (#26).
- A scheduled job stopped mid-run, by `launchctl bootout`, a plist loaded again or a shutdown, now stops its command too, lets go of its locks and leaves a heartbeat saying it was stopped, with exit 143. Before, the command ran on with no watchdog and the next run started beside it. A command left running by a `job.py` killed outright still holds the job's lock and the shared assistant lock, and is stopped by the first fire after its time is up.
- A run caught by a closed lid no longer loses its lock when the Mac wakes past the lock's time: a lock stands while its `job.py` lives, so the overdue fire is skipped instead of running a second copy. A process number reused by another process no longer holds a lock.
- `job.py --timeout 0`, or less, is refused with exit 64 instead of timing out every run; `GARRICK_JOB_TIMEOUT=0` keeps the default, with a line in the log.
- A job's command killed by a signal exits 128 plus its number, as a shell reports it (137 for SIGKILL), and the reason names the signal. It exited 241 or the like before.
- A job's command that exits 4 or 124 itself reads "exited 4", not "could not sign in" or "timed out": those words now come only from `job.py`'s own sign-in check and watchdog.
- The zone guard follows links: a file reached through a link in the project to a folder in another zone is asked about, as that zone.
- The zone guard ignores case on a disk that does, as a Mac's does: `/users/...` or `zones/work/...` no longer slips past it, and the session's own project in another case is no longer asked about.
- Two status page actions at once, from two quick clicks or a click and Ask, could lose one of them: the second read the note before the first was committed, or found git busy and put back a version without the first. Each now waits for the zone's lock. A commit the wall check refuses no longer overwrites an edit you made in Obsidian meanwhile, and the rekey map keeps every update.
- Switching the preview `page-actions` off now stops the buttons at once. Before, a page built while it was on went on acting until it was rebuilt. Ask's park, wake and add need the flag too.
- A wall check that hangs, or a commit waiting for a signing passphrase, no longer leaves a status page action hanging with the note edited and nothing committed: git is stopped after 60 seconds and the note put back.
- A fault in `page_action.py` other than a refusal, such as a file it cannot read, now answers in JSON and is logged, instead of a traceback the app shows as "That did not work."
- *Run now* judged a job's lock by its time alone, so after the Mac slept it could start a job that was still running. It now asks `job.py`, where the jobs extra sits beside the page, and a live run holds its lock.

## [0.14.0] - 2026-10-10

A mail you forward from your own account is read by the people inside it: Outlook's unmarked forwards are understood, and your own addresses, listed under *Me*, carry mail without deciding whose it is.

### Fixed

- A mail forwarded from Outlook is now read for the people inside it. Outlook opens a quoted message with its `From:`, `Sent:` and `To:` lines alone, with no *Forwarded message* line above them, and a plain-text copy loses even its rule; `intake` saw only whoever forwarded it, so their party was suggested and a wall between the people inside went unasked. Unmarked header blocks are read now, after a blank line or a rule, with bold labels (`**From:**`), `>` quoting, `;` between addresses and Outlook's `<a@x<mailto:a@x>>`.

### Added

- Your own addresses, written under *Me* in `System/context.md` (`My addresses: …`). They carry mail and no longer decide whose it is: a mail you forward from your work account is read by the people in it. Your own address's party, an employer say, is still added when no wall stands between it and them, or when nobody else is on the mail, and never in another zone's inbox. `intake.py parse` shows it under `suggested.own`.

## [0.13.0] - 2026-10-10

The status page's Mac app can keep its menu in a panel that slides out from a screen edge or down from under the notch, and the panel's field asks Garrick as well as finding a thread.

### Added

- *Shows as* in the status page app's Settings › Menu bar (preview `menu-bar`): the menu as a panel that slides out from the left or right edge of the screen, or down from under the notch, instead of an icon in the menu bar. The panel is fused to its edge, as the notch is to the top of the screen, and as tall as what it lists. It opens when the pointer rests on the top third of a side edge or on the notch, or with the hotkey. It holds what the menu holds, with each project's threads open under it. See [As a panel](docs/extras/status-page.md#as-a-panel).
- The panel's field finds a project or thread as you type, and offers what you typed as *Ask Garrick*: a click, or Return when nothing matches, opens your default assistant at the workspace root with your words. The panel answers nothing itself and calls no model.
- *Process the Inbox* names where items wait, such as "Work 4 · Meetings 1", in the panel; the page sends each inbox's count with the total.

### Changed

- Settings › Menu bar describes a menu kept at hand outside the window, an icon or a panel: *Show in the menu bar* is now *Show the menu*, and the hotkey opens either.

## [0.12.1] - 2026-10-09

The status page's Mac app builds again with an Xcode older than macOS 27's, and the zone guard no longer stops a session opened in `System/`.

### Changed

- The zone guard (`extras/hooks/zone_guard.py`) no longer stops a session opened in `System/`. `System/` governs every zone and wiki, so a session there works across them without asking, as one at the workspace root already did. `System/rules.md` says so.

### Fixed

- `make-app.sh` failed with an Xcode older than macOS 27's: 0.12.0 kept the menu's icons visible through an API those SDKs do not have. The app now sets it by name, so it builds with any SDK and the icons still show on macOS 27.

## [0.12.0] - 2026-10-09

The status page's Mac app gains Keep awake, Process the Inbox and app icons in its menu bar, and the Garrick band follows the session and works at every level of the workspace.

### Added

- *Process the Inbox* at the top of the status page's menu bar (preview `menu-bar`): how many items wait in the inboxes, and one click to open your default assistant at the workspace root with "process the inbox".
- *Keep awake* in the status page's menu bar (preview `menu-bar`): for an hour, three hours, until turned off, or while Claude Code or Codex is mid-turn, read from their transcripts by the new `extras/status/agents_working.py`. The display can stay on too. The app holds macOS's power assertions itself, so a quit or crash releases them, and the menu bar mark carries an amber dot while it holds the Mac awake.
- [A desktop toolkit](docs/extras/toolkit.md), a page among the extras: the Mac apps the author runs around a workspace, for opening Markdown files, dictating and watching usage, each as a slot any app can fill. It warns that a dictation app's cloud cleanup sends what you said to that model's provider. Garrick ships none of them.

### Changed

- The Garrick band's second line follows the session: once you send a prompt it shows that prompt's first line, and while the assistant works, the step it is on (`Editing register.tsx`, `Run the tests`). Before the first prompt, and after `/clear`, it shows the Resume here line as before.
- The band gains *Finder* (`f`) and *Obsidian* (`o`), which open the thread note. Obsidian is offered only where it is installed and the note sits in a vault. `/garrick finder` and `/garrick obsidian` do the same.
- The band's *Note* pane turns wikilinks and file paths into links a click opens, and offers *Open in Obsidian* and *Reveal in Finder* for the whole note.
- The band's own *Hide* button is gone: the `[-]` beside the band, which is Claude Code's, folds it. `/garrick hide` takes it away and `/garrick` brings it back.
- In the status page's Mac app, a card's ways to open a project or thread are the apps' icons, as in its menu bar: the note's app, Finder, cmux, Codex and Claude, the default on a tinted square, each named when you hover it. The app hands the page the icons, so a browser keeps the words.

### Fixed

- At a project whose resume points live in its threads, the Garrick band offered only *Clear*, because the hub has no Resume here block. It now names the live threads, *Resume* asks where each stands, *Note* shows each thread's block, and *Wrap* wraps the thread the session worked on.
- `/garrick resume` and `/garrick wrap` submitted their prompt from inside the command, which Claude Code refuses because the command holds the turn. They now submit it just after the command answers.
- Outside a thread (in `System/`, at the workspace root or in a wiki), the Garrick band offered only *Clear*. It now offers *Finder* on the folder too, and in a wiki *Obsidian* on its index.
- The Garrick band could lose its thread and show only *Clear*. It looked for the thread note from the shell's current folder, which moves whenever the assistant runs `cd` in a command, so after such a turn it found no note. It now looks from the folder the session started in.
- `/garrick` could leave the band hidden. It toggled the mod's own flag, which knew nothing of Claude Code's `[-]` fold, so after a fold it hid the band instead of showing it. Typed during a turn, it also waited for the turn to end. `/garrick` now always shows the band, `/garrick hide` hides it, and both answer at once.
- The graph's panel offered no *Open in Claude*, *Open in Codex*, *Open in cmux* or *Reveal in Finder* on any note, and no *Park* that acts; a thread's or a project's note there now offers what its card in the list does.

## [0.11.2] - 2026-10-09

The Garrick band resumes the thread, and wraps and clears it.

### Changed

- The Garrick band's *Resume here* button resumes the thread instead of only showing its block: it asks the assistant to read the Resume here block and say where the thread stands and what comes next. The band also gains *Wrap*, which rewrites the block and adds the day's entry, and *Clear*, which runs `/clear`. *Note* still shows the whole block in a pane without calling the model. Each button has a letter, and `/garrick resume`, `/garrick wrap` and `/garrick note` do the same from the prompt.

## [0.11.1] - 2026-10-09

The zone guard: the assistant checks with you before it edits outside the project you opened it in.

### Added

- The zone guard, a hook for Claude Code and Codex in `extras/hooks/zone_guard.py`. Before the assistant edits a file in another project, another zone, a wiki or `System/`, it stops once and names both places. Claude Code asks you in its permission prompt and remembers a place you allow for the rest of the session. Codex hooks can't ask, so the first edit there is refused with the same sentence and a second one goes through. Edits inside the session's project, in its zone's loose files such as `Todo.md`, or outside the workspace go ahead, and so does any session opened at the workspace root. Optional: [its README](extras/hooks/README.md) says how to load it, and the setup skill offers it.

### Changed

- `System/rules.md` adds writing outside the session's project to the things to stop and ask about first. It holds with or without the guard, and covers what the guard can't see, such as a shell command that writes a file.

## [0.11.0] - 2026-10-09

The Garrick band: a Claude Code mod that shows the thread you are in above the prompt.

### Added

- The Garrick band, a Claude Code mod in `extras/mods/garrick-band/` ([#20](https://github.com/iamvenuti/garrick/issues/20)). Above the prompt it draws the mark, the zone, project and thread you are in with its status, and the first line of its Resume here block, with a button for the whole block; `/garrick` hides it. In replies it turns file paths in backticks into links you can Cmd-click. It reads files only and never calls a model. Optional and Claude Code only: [its README](extras/mods/README.md) says how to load it, the setup skill offers it, and CI validates and tests it on Claude Code 2.1.295.

### Changed

- The README plays the walkthrough with the new mark.

## [0.10.0] - 2026-10-09

A new mark, and the Mac app takes Garrick's name.

### Changed

- A new mark: a cabinet of three compartments, a narrow spine on the left, the open one in blue and a closed one beneath it, for work kept in its own place and one thing open at a time. It replaces the *Gr* tile in `docs/assets/garrick-mark.svg`, with a version for dark grounds, a one-colour version, a small cut on the 16 px grid for favicons (`garrick-mark-favicon.svg`, which follows the browser's dark mode), a lockup with the wordmark in Baskervville and a macOS app icon. The blue stays `#3D73E0` on light grounds and takes the deck's lighter `#8EB1F5` on navy. [The mark's note](docs/assets/brand.md) lists the files and colours. The README, the deck, the social card, the adoption ladder, the walkthrough video and the status page all carry it: the page's heading mark follows its light or dark theme, and its tab icon follows the browser's.
- Garrick's Status.app is now **Garrick.app**, and the page it shows is headed *Garrick*. The app's icon is the mark on a navy tile. In the menu bar the mark is drawn in the menu bar's own colours, light or dark, with the open compartment in blue. `make-app.sh` builds `Garrick.app` from `Garrick.swift` and replaces a build of *Garrick's Status.app*; the app keeps its bundle identifier, so its settings, window place, menu and hotkey carry over. If it opened at login, switch *Open at login* off and on again in Settings › Menu bar. Rebuild the app with `make-app.sh` to get it.
- The walkthrough video carries the new mark and says "status page" where it named Garrick's Status; the architecture overview and the docs call it the status page too.

## [0.9.0] - 2026-10-08

Garrick's Status in the menu bar, as a preview: your projects and threads one click from any app.

### Added

- Garrick's Status in the menu bar, behind the `menu-bar` preview flag, in Garrick's Status.app. An icon lists the live projects of the zone the graph shows; pointing at one opens a line of app icons, the ways its card offers to open it, then its threads, each with its own icons. Clicking a project's or a thread's name opens it with the default from Settings, the same as clicking a thread's name in the window. The icon carries the *Status* tab's red dot. Settings › Menu bar switches the icon on, opens the app at login and records a hotkey that opens the menu from any app. With the icon on, closing the window leaves the app in the menu bar. Rebuild the app with `make-app.sh` to get it.

## [0.8.1] - 2026-10-08

Add an action from the status page's Todo list.

### Added

- *＋ Add* on the status page's Todo list, behind the `page-actions` preview flag, in Garrick's Status.app: a new line in a zone's `Todo.md`, with an optional project or thread picked from a tree of the zone and an optional date. Undated lines go to the Inbox; dated ones where a dated line belongs. `page_action.py` gains `todo-add`, and `todo_lines.py` gains `add()`.

## [0.8.0] - 2026-10-08

A cleaner status page: Overview shows the work and nothing else, one row at the top replaces the sidebar, threads fold under their projects, and a preview shows where the assistant's time and money go.

### Added

- *Time* and *Cost* on the status page's Threads card, behind the `effort` preview flag: the same rows show the assistant's active time or list-price cost over the last 30 days, largest first, read from Claude Code's own transcripts with no model call. A line under the columns accounts for what no row shows, so the figures add up. `effort.py --record`, run nightly, keeps each day's totals once the transcripts are cleaned up. Claude Code only for now. ([#17](https://github.com/iamvenuti/garrick/issues/17))

### Changed

- The status page's Threads card has a row per project, with a chevron that unfolds its threads; a project with no thread notes is a row of its own. The fold is remembered. ([#14](https://github.com/iamvenuti/garrick/issues/14))
- The status page's *Overview* is the work alone. The figures at the top (things needing attention, live threads, open actions, files waiting, the check or the assistant's calls) now lead the *Status* tab.
- The status page has no sidebar. One row pinned at the top holds the name, when the page was built, the tabs, rebuild, Settings and the theme, now three icons. A hidden card is listed in Settings › View until it is shown again.

## [0.7.2] - 2026-10-06

Three fixes found on the first update of an adopted workspace.

### Fixed

- An update no longer forgets that a workspace was adopted. A workspace laid out by hand in Garrick's shape and stamped `"from": "adopted"` kept that only until its first update, which replaced it with how the newer Garrick was fetched; the status page then stopped showing the release notes still to come on `main`. The stamp now keeps `adopted`, and each entry in its `updates` says how that Garrick came, as `via`. `check.py --version` names it. ([#10](https://github.com/iamvenuti/garrick/issues/10))
- `check.py` accepts `status: parked` on a project hub. A project with no thread notes is parked as a thread of its own, by saying "park X" or with the status page's *Park* button, and the check then reported an error. ([#11](https://github.com/iamvenuti/garrick/issues/11))
- When the Garrick an update runs from sits inside the workspace it would update, the refusal now says to move the newer Garrick out, unzipped or exported from a clone, instead of asking you to name the workspace you had already named. [Updating Garrick](docs/updating.md) and the `update` skill say the same. ([#12](https://github.com/iamvenuti/garrick/issues/12))

## [0.7.1] - 2026-10-06

The README plays its walkthrough once.

### Fixed

- The README showed the walkthrough twice: GitHub turns every link to an attached video into a player, and the GIF above the walkthrough linked to it. The GIF is gone, and the walkthrough plays once. Nothing in an installed workspace changes.

## [0.7.0] - 2026-10-06

Updates: a newer Garrick now reaches a workspace you have already installed, without losing what you changed. And a first-run setup that looks at your Mac before it asks you anything.

### Added

- `install.py --update ~/Garrick` brings an installed workspace up to the Garrick you run it from, without losing what you changed. It reports first and changes nothing until `--apply`. A file still exactly as some Garrick wrote it is replaced. A file you changed that Garrick has changed too gets Garrick's version beside it as `.new`, committed so a clean or a clone keeps it until you merge. Starting files you have filled in, such as a `Todo.md`, are left alone. `System/rules.md` is always merged, never replaced. Nothing is deleted, each repository gets one commit you can revert, and the version stamp changes last. [Updating Garrick](docs/updating.md) has the details.
- The `update` skill: say "update Garrick" and your assistant runs the update, then merges each `.new` file with you, keeping your changes and Garrick's together and asking about any passage you both changed.
- `check.py` warns while an update's `.new` file waits to be merged, and `check.py --version` says when the workspace was last updated, and from which Garrick.
- The `setup` skill and `System/tools/probe.py`: say "set up Garrick" in a new workspace and your assistant looks at what your Mac has (the assistant apps and commands, cmux, Obsidian, git's settings), asks only what it cannot find, and writes how you work to `System/setup.md`, so every later session knows which tools to suggest and which to leave alone. It offers to fix what is missing, then hands over to the interview. The probe is read-only and sends nothing. The installer's last line now says to start with it.
- The setup skill's *Fill in my resume points* walks you through each thread whose Resume here is still the template's, one question at a time, so the status page and every cold resume start from real answers. `check.py` warns about such threads until they are filled in.
- `release-hashes.json` records every file each release shipped, so an update recognises a file left by any earlier Garrick, even in a workspace installed before 0.4.0 or one where a fix was copied in by hand.

## [0.6.1] - 2026-10-05

A security fix in the intake and meetings skills, and a clearer count of changed files on the status page.

### Changed

- The status page's Repositories card counts changed files and says so: "12 changed files", not "12 uncommitted", which read as twelve commits. Its tooltip and a list under the tiles split them into staged, not staged, untracked and conflicted, and list the paths, with a button that copies the repository's folder. The card stays read-only: nothing on it commits. Untracked files in a new folder are counted one by one.
- `intake.py` lost `zone_of`, which nothing called.

### Fixed

- `todo_lines.py` closes the files it reads, so the tests no longer print `ResourceWarning`.
- The status page's Repositories card says a repository "could not be read" when `git status` fails or runs past 30 seconds, instead of showing it as all committed.

### Security

- The filing commands of the intake and meetings skills, and the meetings skill's person, index and log writes, check where a file will really land and refuse rather than file somewhere else. A symbolic link is followed only while it stays inside the folder that was checked, the project or the wiki; one that leads out of it, into another project or off the workspace, is refused. The file is then written relative to that folder, opened without following any link, so a link put on the way after the check makes the command refuse instead of writing through it. A mail refused partway through filing stays in its inbox, with no draft page left behind. Every such command has boundary tests. Details are in the security advisory published with this release.
- **Breaking for linked folders:** a workspace whose `Wikis/`, a wiki or a zone is a link to another disk or a synced folder outside the workspace can no longer file into it. Keep the workspace itself on that disk instead.

## [0.6.0] - 2026-10-05

The status page is reorganised around how it is used: *Overview* for your work, *Status* for the machinery, the graph one place at a time, and Settings for how a thread opens. Todo lines move to the Obsidian Tasks format, and two preview features, the Todo list and buttons that act, can be switched on.

### Added

- Preview feature `page-actions`: in Garrick's Status.app, tick and date a line of the Todo list, and park or wake a thread from its card. Each button changes one line or one `status:` field and commits it, as the skills do, and a commit the wall check refuses leaves the file as it was. `extras/status/page_action.py` does the work; a browser cannot reach it.
- With `page-actions` on, a scheduled job of the jobs extra gets *Run now*, which starts it through launchd so it keeps its own wrapper, lock and log.

### Changed

- The page has tabs. *Overview* is where your work stands: the tiles, the graph, the threads, open actions and inboxes. *Status* is the machinery behind it: scheduled jobs, assistant calls, the check, repositories and wikis, with a red dot on the tab when something there failed, and *Needs attention* at its top. The sidebar lists them in that order. Every tile on *Overview*, and the summary at the top of the sidebar, opens the card that explains it, in whichever tab it sits. A card's header has a button that moves it to the other tab, and *Reset view* puts every card back.
- *Settings* lists the ways to open a thread: the note's own link (*Open in Obsidian*, or *Open the note* without Obsidian), *Reveal in Finder*, cmux, Codex and Claude. Each has a checkbox, whether the cards offer it, and a radio button, what clicking a thread's name does; the note's link is the default. Settings closes with the × at its top right, and every change is kept as it is made.
- *Park* and *Wake* sit at the top right of a thread's card and the graph's panel, beside the name, rather than among the ways to open it. *Pause rotation* and *Fit* sit in the graph's bottom right corner. Closing Settings after a change rebuilds the page in the Mac app. The sidebar's *Problems only* became *Only what needs attention*, at the top of the *Status* tab, and acts on that tab alone.
- The graph shows one place at a time, Work first: a drop-down in its bar picks a zone, a wiki, or *All*, and the page remembers the pick. The graph's and the threads' counts sit under their legends rather than in the card headers, and the legends are shorter.
- The Todo list (preview `todo-list`) is a tab of its own beside the overview, as it is in the workspace it came from, with a red dot when something is overdue. A link in the sidebar opens the tab its section is in.
- The sidebar's top row holds Garrick's mark, the page's name and two icons: a circular arrow that rebuilds the page in the Mac app, or copies the command that does in a browser, and the cog for Settings. The build time sits below them across the sidebar. *Reset view* moved into Settings, and it no longer forgets which apps you chose to open projects in.
- The status page reads a project with no thread note as its own single thread, from its hub, so a workspace laid out before Garrick gave every project a `Threads/` folder shows every project. `dormant`, `paused` and `on-hold` read as parked, and `closed`, `archived` and `complete` as done.
- A zone's `Todo.md` uses Obsidian Tasks lines: each opens with its thread, `[[Thread]]: `, or its single-thread project, or else its party or person, and the dates go last as Tasks fields (`📅` due, `🛫` not before, `#waiting` and `⏳` the day to chase). Obsidian's Tasks plugin can then sort and filter them, and the status page's Todo list shows their dates. The meetings, threads and interview skills write it; the template's header explains it. A list in the older `· project, thread · date` form still counts on the page, without dates.

## [0.5.0] - 2026-10-05

The status page opens a project in Claude, Codex or cmux, shows the release notes of the Garrick you installed, and has preview features you can switch on.

### Added

- The status page opens a project or thread in Claude, Codex or cmux. Each build checks which of the three this Mac has. In *Settings*, under *Open projects in*, you switch each installed one on or off, and every app left on gets a button on the cards, in Garrick's Status.app only. Claude starts a session with "open Pricing" typed in for you to send. Codex and cmux open the folder with the phrase on the clipboard. Your choices are kept in the app's own storage.
- *Settings* shows the installed release's notes from `System/garrick-changelog.md`, which the installer now copies from `CHANGELOG.md`, so nothing is fetched. A workspace that follows `main` also sees what is coming next. An *Announcements* link leads to the release news on GitHub.
- Preview features: in Garrick's source but not yet released, off until switched on in `System/garrick-flags.json`, and listed in *Settings*. The first is `todo-list`, a card with every open action in the zones, overdue first, read from the notes and never written.

### Changed

- *Settings* opens from a cog beside the page's name, not from a sidebar button.
- Garrick's Status.app needs `make-app.sh` run again to open Claude and Codex. Until then it opens cmux as before, and its Claude and Codex buttons do nothing.

## [0.4.0] - 2026-10-04

Every install now records what Garrick wrote, so a later update can tell the user's edits from Garrick's own files; and the status page gains Settings, with About Garrick and the ways to report a problem.

### Added

- The version stamp, `System/garrick-version.json`, now lists every file Garrick wrote into the workspace, by path and SHA-256: the installer's files, and those of a zone `scaffold.py zone` adds later. A future update can then replace a file that is still as Garrick wrote it and leave one the user has changed for a merge. `System/context.md`, which holds the user's own answers, is never listed. A workspace installed before this has no list, so an update will treat all its files as the user's.
- `check.py --version` adds how many of those files have changed since, or are gone: counts only, since a path names a zone and a zone's name can be a client's. Still one line.
- The status page has *Settings*, and the Mac app has *Settings…* (⌘,). Under *About Garrick* it shows the installed version, as `check.py --version` says it. It also links to GitHub to report a bug (the form arrives with the version filled in), report a wrong refusal, suggest a change, ask a question, or see what's new. Without a GitHub account, you can copy a report to send instead. The links open in the browser. The page still loads nothing and sends nothing, and it never checks for updates. In the Mac app, the menu item arrives once `make-app.sh` is run again; the page's own Settings button works without that.

## [0.3.1] - 2026-10-04

New wording: Garrick as an AI chief of staff that remembers your work and knows whose confidences you hold, running on the agent you already use.

### Changed

- The README opens with "Garrick remembers your work and knows whose confidences you hold", then "An AI chief of staff for your knowledge work, running on the agent you already use. Everything stays in files you own." Claude Code or Codex is described as the agent underneath. The GitHub description, the social card and the deck's cover and claim slide say the same.
- The launch walkthrough is re-cut with that wording at the opening, in the first app scene and at the close. The rest of the walkthrough is unchanged; captions in `docs/assets/garrick-launch-video.srt`.

## [0.3.0] - 2026-10-04

The status page in a Mac app of its own, and a page that offers Obsidian and cmux only where the machine has them.

### Added

- *Garrick's Status.app*, in `extras/status/app/`: the status page in a window of its own, for the Dock and the app launcher, built on the user's Mac by `make-app.sh` from one Swift file. It rebuilds the page when it is more than 30 minutes old, reloads it when it is rewritten, turns the sidebar's button into *Rebuild now*, and sends links to the app macOS uses for them. `--check` tests it without a window.
- On the status page, inside the app and where cmux is installed, project and thread cards offer *Open in cmux*: a cmux tab in that folder, with "open [thread]" on the clipboard. It opens the folder as Finder would, with no access to cmux's controls. `--no-cmux` leaves it out.

### Changed

- The status page asks this machine what it has at every build. Links open a note in the Obsidian vault closest to it, read from Obsidian's own list of vaults, whether that is the workspace root or a zone or wiki opened on its own, and as a file otherwise; `--obsidian VAULT` still names the root vault, and `--no-obsidian` keeps file links. A workspace with no `Todo.md` gets no Open actions card, tile or sidebar line, and the tiles fill their row whatever their number.

## [0.2.0] - 2026-10-04

The release for the first invited users: guided onboarding for the desktop apps, parking, the status page, scheduled jobs, the interview skill, a stricter wall check, and a version stamp in every workspace.

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

[Unreleased]: https://github.com/iamvenuti/garrick/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/iamvenuti/garrick/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/iamvenuti/garrick/compare/v0.12.1...v0.13.0
[0.12.1]: https://github.com/iamvenuti/garrick/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/iamvenuti/garrick/compare/v0.11.2...v0.12.0
[0.11.2]: https://github.com/iamvenuti/garrick/compare/v0.11.1...v0.11.2
[0.11.1]: https://github.com/iamvenuti/garrick/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/iamvenuti/garrick/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/iamvenuti/garrick/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/iamvenuti/garrick/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/iamvenuti/garrick/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/iamvenuti/garrick/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/iamvenuti/garrick/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/iamvenuti/garrick/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/iamvenuti/garrick/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/iamvenuti/garrick/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/iamvenuti/garrick/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/iamvenuti/garrick/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/iamvenuti/garrick/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/iamvenuti/garrick/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/iamvenuti/garrick/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/iamvenuti/garrick/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/iamvenuti/garrick/releases/tag/v0.1.0
