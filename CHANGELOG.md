# Changelog

What changed in each release. Dates are when the release was tagged. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- The `interview` skill: "interview me" opens with questions one at a time, including whose confidences you hold and which must never meet, keeps a record in `System/interviews/`, then proposes parties, walls, projects, threads and open actions and sets up only what you accept. Offered as an optional first step of the first session.
- `extras/jobs/`, optional and outside core: an assistant on a schedule. One runner for Claude or Codex, picked by `GARRICK_HARNESS`, with tiers instead of model names; a wrapper with log, heartbeat, lock, watchdog, sign-in check and idle alarm; a ledger of every call with daily, hourly and cost caps; a deny profile so an unattended Claude cannot send, share, delete or edit `System/`, loaded with user and project settings only; and an example job, a "what's open" brief per zone, with a launchd plist.

- `extras/status/`, optional and outside core: a status page. One self-contained HTML file with every live thread by zone and how long since it moved, what the check finds, open actions, what is waiting in the inboxes, and, with the jobs extra, a fourteen-day strip per job and the spend against its caps. Names, parties, dates and counts only, never what a note says; written to `System/generated/status.html`; links open the files, or Obsidian with `--obsidian VAULT`; nothing from the network. With a launchd plist for a nightly rebuild.
- Parking a thread: "park X" sets it aside with `status: parked`, out of "what's open" and out of the Resume-links check, with its note untouched; "wake X" brings it back and "what's parked" lists them. The status page folds parked threads into their own group, and its buttons copy the phrase to say ("open Pricing", "park Pricing", "wake Pricing") or the rebuild command.
- `System/generated/`, for pages a tool rebuilds. The installer's root `.gitignore` names it; `check.py` reports a generated file that is committed or a `.gitignore` without the line, and never reads the folder as wording shared by every side, so a page that gathers every zone cannot exempt anything from the wall check.
- `check.py` warns when a link or a file path in a live thread's Resume here block leads nowhere, so a deliverable renamed or moved shows up in the next check, not in the next cold resume.

### Changed

- Separate desktop and terminal onboarding routes, with a shared first session that files one conversation, produces a brief and verifies resuming from a fresh chat.
- Guided setup brings real use and a fictional wall demonstration into the first session. Obsidian, cmux, mail fetching and phone access are optional follow-ons.
- Clarify declared pairwise walls, supported checks and their limits. Lead with continuity of work and local ownership instead of an absolute confidentiality claim.
- Document Codex remote voice on iPhone with its desktop host requirement, and Claude Code Remote Control from a terminal.

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
