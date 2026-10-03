# Getting started: command reference

For everyday app use, follow [Desktop first steps](first-steps.md), then [Your first useful session](first-session.md). For a CLI workflow, start with [Terminal setup](terminal-setup.md). This page is the detailed reference for the installer and workspace tools; your assistant can run them for you.

Requires macOS, Python 3.9 or later, and git. If `git --version` fails, run `xcode-select --install` and wait for it to finish. You also need Claude Code or Codex. Claude Code reads `AGENTS.md` natively from version 2.1.277; `claude --version` tells you which one you have.

## Install

From the folder you downloaded or cloned Garrick into:

```sh
python3 install.py
```

This asks a few questions, one at a time: where the workspace should go (default `~/Garrick`; a folder name on its own, such as `Garrick-work`, goes in your home folder), your name and a one-line description of what you do, your zones (default `Work, Personal`), what each zone holds, then your parties, walls, people and dictation aliases. Press Enter to accept the default in brackets, or skip a section by answering nothing. A party is an organisation or person whose confidences you hold, and each gets a one-word tag and, if you like, the domains its mail comes from, such as `acmecorp.example`. Leave personal webmail out: a Gmail address never names a party. A wall is an explicit pair of tags whose material must not be used in each other's projects; the installer only asks about walls once you have named two parties. Separate folders and different party tags do not create walls automatically. For two confidential internal projects, use two party tags and declare a wall between them. You can start with the parties relevant to your first project and add others later.

To skip the questions (for a demo, a test, or a guided session), pass a config file:

```sh
python3 install.py --config examples/acme.json --target ~/Garrick-demo
```

`examples/acme.json` is a complete fictional setup (an advisor with two clients, Acme Corp and Birch & Co, walled from each other). Copy it and edit it as a starting point for your own config.

The installer writes only inside the target folder. It refuses a target that is your home folder, sits under `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Library` (macOS blocks scheduled jobs from reading those), overlaps the folder Garrick came in (that folder, one inside it, or one holding it), or already has files in it. It compares the folders themselves, not their names: on a Mac, `~/garrick` and `~/Garrick` are the same folder. `--force` lets it install next to files that are already there, but it still stops if the folder holds an `AGENTS.md`, `System`, `Zones`, `Wikis`, `.git`, `.gitignore`, `.claude` or `.agents`.

## What you get

```
AGENTS.md               entry point for any assistant
.claude/skills          link to System/skills, for Claude Code
.agents/skills          link to System/skills, for Codex
System/
  rules.md              how the assistant behaves (the only copy)
  context.md            who you are and who you deal with, filled in from your answers
  templates/            the project and thread notes scaffold.py copies
  tools/                scaffold.py, check.py, and garrick_lib.py, which they share
  skills/               threads, intake, meetings, knowledge
Wikis/                  its own git repository
  Meetings/             every conversation, empty until you feed it
  Knowledge/            published material you study, empty until you feed it
Zones/<Zone>/           one folder and one git repository per zone you named
  AGENTS.md
  Todo.md
  Inbox/                mail and files waiting to be sorted; never committed here
```

The root, `Wikis/`, and each zone are separate git repositories, each with a first commit already made. `System/skills` is symlinked into `.claude/skills` and `.agents/skills` in every one of those repositories, so Claude Code and Codex both find the skills wherever a session starts.

If git had no email configured on your machine, the installer sets `user.name` to the name you gave it and `user.email` to `garrick@localhost`, just inside these new repositories. Those local settings win over any global one you add later. To use your own address, set it globally with `git config --global user.email "you@example.com"`, then remove the local settings in each repository, for example `git -C Zones/Work config --unset user.email` and the same for `user.name`, for the root, `Wikis` and every zone.

## Your first project

A project always starts with its first thread, and both need a party tag from the Parties table in `System/context.md`. The commands below use `acme`, which exists in the demo workspace; on your own install, use one of your own tags. From the workspace root:

```sh
python3 System/tools/scaffold.py project --zone Work --name "Acme" --party acme --thread "Pricing"
```

This creates `Zones/Work/Acme/`, its hub note, `Sources/`, `Deliverables/`, and the first thread at `Zones/Work/Acme/Threads/Pricing/Pricing.md`, then lists the thread in the hub. A later thread in the same project:

```sh
python3 System/tools/scaffold.py thread --zone Work --project "Acme" --name "Supplier Audit"
```

The script checks names before it creates anything: no digits or punctuation (they can't be said aloud), and no name that already exists or sounds too close to a sibling. It refuses with a one-line reason rather than write something broken.

The script does not commit. Each zone is its own git repository, so commit there:

```sh
git -C Zones/Work add Acme
git -C Zones/Work commit -m "New project Acme"
```

Working with an assistant instead of the command line, just ask: "new project Acme for acme in Work, first thread pricing." The `threads` skill resolves the request, runs the script and commits for you. If the party doesn't exist yet, it offers to add a row to `System/context.md` first, and asks whether a wall belongs between it and any existing party.

## Opening and wrapping

Open a terminal in the workspace and start your assistant: `cd ~/Garrick`, then `claude` or `codex`. A zone or `Wikis/` works as a starting folder too; each is its own repository and carries the skill links.

- **"Open Acme pricing"** reads that thread's Resume here block and answers in two sentences: where it stands, and the next action.
- **"Wrap Acme pricing"** (or "close X") rewrites that block so it describes now, adds a dated entry below it, moves any open actions into the zone's `Todo.md`, and commits the change in that zone's repository.
- **"Close for the day"** does this for every thread touched today, one commit each.

A thread that was just created has no history, so opening it only tells you its Resume here block is still blank. Do some work, wrap it, and the next open has something to say.

The full procedure, including how it resolves a mangled or ambiguous name, is `System/skills/threads/SKILL.md`.

## The check

For app users, ask “Run the workspace check and explain any findings.” The command below does the same. A clean result covers the implemented checks, not a guarantee against every disclosure; see [coverage and limits](principles.md#what-the-check-covers).

```sh
python3 System/tools/check.py
```

Tests the workspace against every rule a machine can check:

- a `CLAUDE.md` in or above the workspace, which stops Claude Code reading `AGENTS.md`;
- instruction files that drift: an `AGENTS.md` past its word budget, the same sentence copied into two instruction files, or a hand-written list of skills that no longer matches `System/skills/` (warnings);
- installer placeholders left unfilled;
- a wall or a person in `System/context.md` naming a tag that is not in Parties, or a mail domain that is personal webmail or listed for two parties (a warning);
- a zone that is not its own git repository, or has no `AGENTS.md` or `Todo.md`, or no pre-commit wall check (a warning; `--install-hooks` puts it back), or no `Inbox/` (a warning);
- names that cannot be said aloud, or siblings that sound alike;
- project and thread notes missing their frontmatter or required sections, or naming a party that is not in `System/context.md`;
- deliverables without a date prefix;
- meeting and mail pages missing a zone or parties;
- anything committed from a zone's `Inbox/` (the pre-commit hook refuses it too), a recording there instead of its transcript, or a copy left behind after an item was filed;
- a file in a project's `Sources/` that came from mail with no finished page in Meetings: an attachment, found by its exact bytes, or a whole saved mail;
- a project file that crosses a wall: it links to a meeting page the wall should have kept out, names a party, person or alias from the far side (files in `Sources/`, which came from the party itself, are exempt from this one), repeats eight or more words in a row from a walled meeting page or its raw transcript, or is an attachment of a mail from the far side. The finding names the file and the walled party, never the words that matched;
- a Knowledge page that links into Meetings, or carries `parties` or a `zone`;
- a raw record changed after it was filed.

It reports two kinds of finding. An error breaks a rule; a warning is something to look at, such as a deliverable without its date or a project without a party. Plain text by default, grouped by check; add `--ear` for a three-sentence version meant to be read aloud, or `--json` for another program to consume. The exit code is 1 if there is at least one error and 0 otherwise, warnings included.

The walls part also runs before every commit. The installer puts a git hook in each zone that runs `check.py --staged --walls-only` on the files being committed, as they are staged, and refuses the commit with one line naming the file and the wall. Take the material out and commit again. `git commit --no-verify` skips the check; it exists for the rare deliberate case, and your assistant is told never to use it unless you ask.

## The two memories

`Wikis/Meetings/` and `Wikis/Knowledge/` are empty after install. Their schemas (what a page needs, where raw material goes, what must never cross between them) are in each folder's own `AGENTS.md`.

Everything comes in through an inbox. Drop a transcript from any recorder (a `.txt`, `.md` or `.vtt` file, not the audio) into `Wikis/Meetings/raw/inbox/`, and mail (a `.eml` file, or the message saved as `.txt` or `.md`) or any other file into a zone's `Inbox/`. Then say "process the inbox". The `intake` skill sorts each item by the *Ways in* rules in `System/rules.md`: a conversation goes to Meetings, through the `meetings` skill; something to read goes to Knowledge, through the `knowledge` skill; material for a project goes into that project's `Sources/`, with the mail it came in kept in Meetings. It asks for the zone, the parties or the project when they are not obvious, goes by the mail domains in the Parties table, and records any you teach it. Ways to fetch mail into an inbox without doing it by hand are in [ways in](extras/ways-in.md).

You can also hand over a link, a PDF or pasted text and say "read this": the `knowledge` skill freezes the original into `raw/` and writes the pages. "Prep me for Acme" and "what does my library say about X" read them back.
