# Extras

Start with [one useful session](../first-session.md) in your app or terminal assistant. Add an extra when you know what it would help you do. Obsidian is for browsing, cmux is for terminal sessions, and phone access connects to the computer holding your workspace. Neither Obsidian nor cmux requires a provider's desktop app; the documented Codex remote voice route does.

Everything on this page is optional. Core Garrick, the folder structure, `AGENTS.md`, `System/rules.md`, `System/context.md`, the installer, the scaffold and check scripts, the skills in `System/skills`, never depends on any of it. None of it is installed by `install.py`, including the code this repository ships for three of them: the IMAP fetcher in `extras/fetch/`, the scheduled-job runner in `extras/jobs/` and the status page in `extras/status/`. Each is a tool you can point at a Garrick workspace because the workspace is just files on disk, and none of them is required to get value from Garrick on day one.

- [Obsidian](obsidian.md), for reading and browsing the workspace as a linked vault.
- [cmux](cmux.md), for one terminal tab per thread.
- [A meeting recorder](meeting-recorder.md), for feeding the Meetings wiki's inbox.
- [Ways in](ways-in.md), for fetching mail into a zone's inbox without doing it by hand: your assistant's own mail connector, the IMAP script in `extras/fetch/`, or a mail rule. It also sets out where core sorts what arrives.
- [Phone access](phone-access.md), through the assistants' own remote features.
- [Scheduled jobs](scheduled-jobs.md), for running the check without being asked, or an assistant on a schedule: a morning brief per zone, with a spend cap and nothing allowed to send.
- [A status page](status-page.md): one HTML file that shows every live thread, what the check found, what is waiting in the inboxes and how your jobs ran. It reads and never stores. It shows names, tags, dates, counts, check findings and the targets of links, and leaves the rest of a note's body out. It opens in a browser or in Garrick, a small Mac app, with *Overview* and *Status* tabs, and offers Obsidian, Finder, Claude, Codex and cmux only where they are installed.

If you strip every one of these away, a Garrick workspace still installs, still opens and wraps threads, still checks itself, and still applies its declared wall rules and commit checks, within the [documented limits](../principles.md#what-the-check-covers). What you lose, in each case, is named on that extra's own page.
