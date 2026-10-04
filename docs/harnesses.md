# Claude Code and Codex

Choose the interface separately from the workspace: [desktop apps](first-steps.md) for a guided start, or [CLI tools](terminal-setup.md) for terminal users. Obsidian and cmux are optional. A provider desktop app is not needed for local CLI work. [Phone access](extras/phone-access.md) differs by provider: Codex's remote voice goes through the ChatGPT desktop app as its host, and Claude Code's Remote Control runs from a terminal session.

Garrick is written for both. No rule, template or skill names either one. The harness-specific pieces are two symlinks per repository and one warning about `CLAUDE.md` files, described below.

## The entry point

Every repository the installer creates, the root, `Wikis/`, and each zone, gets an `AGENTS.md`. That file is the one instruction file name this workspace uses. `template/AGENTS.md` says it plainly: never create a `CLAUDE.md` anywhere under the workspace, because Claude Code stops reading every `AGENTS.md` the moment one exists. `System/tools/check.py` enforces this: it flags any `CLAUDE.md` or `CLAUDE.local.md` inside the workspace as an error, and warns about one sitting above the workspace too, since that can block Claude Code from reading `AGENTS.md` here at all. Your own `~/.claude/CLAUDE.md` is left alone.

Claude Code reads `AGENTS.md` natively from version 2.1.277. The Code tab of the Claude desktop app runs the same Claude Code, bundled inside the app, and reads the same `AGENTS.md`, skills and settings: on version 2.1.284 it loaded the workspace's `AGENTS.md`, found all four skills, and answered "what's open" from the demo. Choose **Local** and the workspace folder itself; [First steps](first-steps.md) has the settings. Codex reads `AGENTS.md` files too, but only from the git repository root down to the folder a session opens in. It won't walk up past a repository boundary to find one. The Codex mode of the ChatGPT desktop app runs the same Codex, bundled inside the app: on version 0.159.2, opened on the demo workspace, it loaded the root `AGENTS.md` and found all four skills. Five skills ship now; both runs predate the fifth. Open the workspace folder itself as the project's source folder, on **This computer**; [First steps](first-steps.md#using-codex-instead) has the settings.

## What has been tested

Both assistants read the same files, but that alone does not show they do the same things with them. This table records what has been checked in each one, with the version it was checked on. A row reading *not yet tested* has not been.

| Capability | Claude Code | Codex |
|---|---|---|
| Reads the workspace's `AGENTS.md` | Natively from 2.1.277. The desktop app's Code tab, 2.1.284, loaded it on the demo | The ChatGPT app's Codex mode, 0.159.2, loaded the root `AGENTS.md` on the demo |
| Finds the skills | 2.1.284 found the four skills then shipped; not yet rechecked with five | 0.159.2 found the four skills then shipped; not yet rechecked with five |
| Picks up a thread cold, in a fresh session | 2.1.284 answered "what's open" from the demo. Resuming a thread wrapped by the other assistant: not yet tested | Not yet tested |
| First-session approvals, on a clean account | Not yet tested | Not yet tested |
| Unattended jobs | 2.1.287 and 2.1.288: the allow list, the deny profile, the settings sources and the permission mode, checked by hand | 0.160.0: a job that only reads ran read-only, writing nothing and with no connector, browser or web tools. Not yet run end to end through `job.py` |
| Connectors in a job | Not yet tested live | Switched off for a job that only reads (0.160.0). With a job that writes: not yet tested |

[Scheduled jobs](extras/scheduled-jobs.md) gives the details of each check. Another assistant counts as supported once it passes the same rows; following `AGENTS.md` alone does not establish it.

## Why each zone is its own git repository

Zones never mix in storage. Giving each zone its own repository makes that true of the history as well: a commit can't span Work and Personal, and a zone can be backed up, moved or handed over without taking the others with it.

The price is that an assistant which stops at a repository's root sees less from inside a zone. Codex is one. A Codex session opened anywhere inside `Zones/Work` reads `Zones/Work/AGENTS.md`, because that is its repository's root file. It does not reach the workspace root's `AGENTS.md`, `System/rules.md` or `System/context.md`, because those sit in a different repository.

That's why each zone's `AGENTS.md`, from `template/System/templates/zone/AGENTS.md`, opens with an explicit pointer: "Before anything else, read `../../AGENTS.md`, `../../System/rules.md` and `../../System/context.md`: an assistant started in this folder may not load them on its own." `Wikis/AGENTS.md` carries the same line, pointing one level up. Claude Code reads instruction files in the folders above as well, past the repository boundary. The pointer is there for an assistant that stops at the boundary, and costs the other nothing to follow.

## Skill discovery

Claude Code looks for skills in `.claude/skills`, and Codex in `.agents/skills`, walking from the session's folder up to its repository root. Since a Garrick workspace is several repositories, not one, the installer creates both symlinks, pointing at the one real `System/skills` folder, in every repository: the root, `Wikis/`, and each zone. Open a session anywhere in the workspace, in either harness, and it finds the same skills, because it's the same folder, linked in from wherever it needs to be reachable.

## What this buys you

Nothing in `System/rules.md`, `System/context.md`, the templates, or the skills refers to either assistant by name. The three-level hierarchy, the wall checks, the resume points, none of it is implemented as a Claude Code feature or a Codex feature; all of it is plain files and a few Python scripts that don't care which one is reading them. Moving from one to the other, or running both against the same workspace on different days, preserves the files and local git history.

## Switching assistants

Both assistants read the same `AGENTS.md` files, the same skills and the same notes, so either can pick up work the other left.

- **Finish one session before you start the other assistant in the same folder.** Two assistants writing the same notes at once can overwrite each other's changes. Wrap the thread first, with "wrap Acme pricing": its resume point and the git history then hold where the work stands.
- **Conversation history stays with the assistant that recorded it.** Neither can open the other's conversations. Each resumes its own with its own command, typed in the folder the session ran in: `claude --resume <id>`, or `claude --continue` for the most recent conversation; `codex resume <id>`, or `codex resume --last`.
- **"Open Acme pricing" works in either.** It rebuilds the context from the thread's Resume here block, which both read, so a fresh session in the other assistant starts where the last one wrapped.

App settings and permissions also belong to each assistant separately. Set them once in each: [First steps](first-steps.md) has both.
