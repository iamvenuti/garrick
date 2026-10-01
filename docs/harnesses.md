# Claude Code and Codex

Garrick is written for both. No rule, template or skill names either one. The harness-specific pieces are two symlinks per repository and one warning about `CLAUDE.md` files, described below.

## The entry point

Every repository the installer creates, the root, `Wikis/`, and each zone, gets an `AGENTS.md`. That file is the one instruction file name this workspace uses. `template/AGENTS.md` says it plainly: never create a `CLAUDE.md` anywhere under the workspace, because Claude Code stops reading every `AGENTS.md` the moment one exists. `System/tools/check.py` enforces this: it flags any `CLAUDE.md` or `CLAUDE.local.md` inside the workspace as an error, and warns about one sitting above the workspace too, since that can block Claude Code from reading `AGENTS.md` here at all. Your own `~/.claude/CLAUDE.md` is left alone.

Claude Code reads `AGENTS.md` natively from version 2.1.277. The Code tab of the Claude desktop app runs the same Claude Code, bundled inside the app, and reads the same `AGENTS.md`, skills and settings: on version 2.1.284 it loaded the workspace's `AGENTS.md`, found all four skills, and answered "what's open" from the demo. Choose **Local** and the workspace folder itself; [First steps](first-steps.md) has the settings. Codex reads `AGENTS.md` files too, but only from the git repository root down to the folder a session opens in. It won't walk up past a repository boundary to find one. The Codex mode of the ChatGPT desktop app runs the same Codex, bundled inside the app: on version 0.159.2, opened on the demo workspace, it loaded the root `AGENTS.md` and found all four skills. Open the workspace folder itself as the project's source folder, on **This computer**; [First steps](first-steps.md#using-codex-instead) has the settings.

## Why each zone is its own git repository

Zones never mix in storage. Giving each zone its own repository makes that true of the history as well: a commit can't span Work and Personal, and a zone can be backed up, moved or handed over without taking the others with it.

The price is paid with Codex. A Codex session opened anywhere inside `Zones/Work` reads `Zones/Work/AGENTS.md`, because that is its repository's root file. It does not reach the workspace root's `AGENTS.md`, `System/rules.md` or `System/context.md`, because those sit in a different repository.

That's why `template/Zones/_zone/AGENTS.md` opens with an explicit pointer: "Before anything else, read `../../AGENTS.md`, `../../System/rules.md` and `../../System/context.md`: an assistant started in this folder may not load them on its own." `Wikis/AGENTS.md` carries the same line, pointing one level up. Claude Code is not bound by the repository boundary in the same way; the pointer is there for the harness that is, and costs Claude Code nothing to follow.

## Skill discovery

Claude Code looks for skills in `.claude/skills`, and Codex in `.agents/skills`, walking from the session's folder up to its repository root. Since a Garrick workspace is several repositories, not one, the installer creates both symlinks, pointing at the one real `System/skills` folder, in every repository: the root, `Wikis/`, and each zone. Open a session anywhere in the workspace, in either harness, and it finds the same skills, because it's the same folder, linked in from wherever it needs to be reachable.

## What this buys you

Nothing in `System/rules.md`, `System/context.md`, the templates, or the skills refers to either assistant by name. The three-level hierarchy, the wall checks, the resume points, none of it is implemented as a Claude Code feature or a Codex feature; all of it is plain files and a few Python scripts that don't care which one is reading them. Moving from one to the other, or running both against the same workspace on different days, costs nothing beyond opening a different terminal.
