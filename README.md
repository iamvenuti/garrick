<picture><source media="(prefers-color-scheme: dark)" srcset="docs/assets/garrick-mark-on-navy.svg"><img src="docs/assets/garrick-mark.svg" alt="Garrick's mark: a cabinet of three compartments, one of them open" width="96" align="right"></picture>

# Garrick

[![Tests](https://github.com/iamvenuti/garrick/actions/workflows/tests.yml/badge.svg)](https://github.com/iamvenuti/garrick/actions/workflows/tests.yml) [![MIT licence](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE) ![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

**Leave any piece of work. Come back to the next action.**

Garrick keeps track of where each piece of your work stands. It reads what comes in, keeps it up to date, and lets finished work step aside, so Claude picks up where you stopped.

Your assistant remembers your projects. It can't tell you which piece of work is waiting on you, what comes next, or what was only in your head when you stopped. Garrick can: every piece of work has one place that says where it stands, written when you leave it and read when you come back. Say “hold this” when someone interrupts you and “back” when you return.

The [Garrick app](docs/extras/simple-home.md)'s home lists your work, most recent first, each with its next action. Continue opens Claude's desktop app on that piece of work, with Claude's answer already on screen. Ask something reaches across all of your work, and Needs you holds only the questions Garrick is waiting on you to answer.

Behind the home, Garrick keeps a record of each piece of work. It files what comes in, such as mail, transcripts and documents, and a piece of work's page shows which of its files are new, changed or missing since you last continued. It keeps the record up to date and asks before it corrects anything written there. Finished work steps aside without anything in it being lost, and old meetings and reading fade out of the way in stages, still findable.

When some of your work comes from people whose confidences you hold, such as two clients or a client and your employer, you can declare walls between them. The agent gets rules for what may not cross, and a check runs before every commit.

Your folders stay as they are. Garrick reads them and writes nothing there unless you ask it to move the files in. Its own record is plain Markdown in folders on your Mac, and updates keep your edits. Claude does the work underneath. Codex works too, in its app or a terminal, without the home's Continue.

https://github.com/user-attachments/assets/7c05ec23-577d-4bf2-9275-81f9b70767cc

*The walkthrough, 98 seconds, with [captions](docs/assets/garrick-launch-video.srt). Dramatised with fictional data; it illustrates the intended workflow.*

## Start small

![Start small. Climb when you want to. Level 1, Organise: Claude or Codex in its desktop app and the Garrick folders, for a resume point for every piece of work, meetings and knowledge kept locally, and walls between the parties you declare. Level 2, Feed it: inbox folders, mail alias ingestion and recorder transcripts, so conversations and mail are filed for you. Level 3, Own the interface: Obsidian to browse, cmux for parallel sessions and the status page to see it all, so your work no longer lives inside one vendor's app and one page shows where it all stands. Level 4, Work from anywhere: the assistants' remote and voice features, so your workspace answers from your phone. Each level works on its own.](docs/assets/adoption-ladder.png)

1. **Organise:** [first steps](docs/first-steps.md), then [your first useful session](docs/first-session.md).
2. **Feed it:** [ways in](docs/extras/ways-in.md) for mail and files, and [a meeting recorder](docs/extras/meeting-recorder.md).
3. **Own the interface:** [terminal setup](docs/terminal-setup.md), [Obsidian](docs/extras/obsidian.md), [cmux](docs/extras/cmux.md) and [the Garrick App](docs/extras/status-page.md).
4. **Work from anywhere:** [phone access](docs/extras/phone-access.md).

## Choose how you work

Both routes use the same files, rules and skills. You can change routes later.

| If you prefer… | Start here | What you need |
|---|---|---|
| A normal app window, with help setting up if wanted | [Desktop first steps](docs/first-steps.md), or a [guided session](docs/guided-session.md) | Claude's desktop app in its Code tab, or Codex in the ChatGPT desktop app. Terminal is used for installation; daily work happens in the app. |
| A terminal and tools you choose yourself | [Terminal setup](docs/terminal-setup.md) | Claude Code or Codex CLI. A provider's desktop app is optional. Add Obsidian for browsing or cmux for several sessions when useful. |

Already set up? [Your first useful session](docs/first-session.md) takes one conversation through filing, a brief and a saved next action. Start with one project; add the rest as you need it.

[Phone access](docs/extras/phone-access.md) is optional for either route. For example, Codex remote voice on iPhone can answer from your Garrick workspace while your laptop is at home, awake and connected. That route needs the ChatGPT desktop host app even if you normally work in a terminal.

## What Garrick keeps for you

- **A place to resume.** Each line of work has a note with the current decision, next action and deadline. Say “wrap it” before leaving, “hold this” when you're interrupted, and “open [thread]” or “back” when you return.
- **Two kinds of memory.** Meetings keeps conversations and correspondence with their sources. Knowledge keeps published material you read. [How Garrick keeps context](docs/context.md) shows how a conversation, a correction and an old page are each handled.
- **Declared information boundaries.** You choose which pairs of parties must be kept apart. The assistant checks those rules before using a conversation for a project. In supported text files, a commit check catches links and names from across a wall, and wording copied from a walled meeting, its transcript or another party's project files.
- **Files you own.** Notes and history stay in the workspace. Claude Code and Codex can read the same record; their private chat history and app settings are separate.
- **Short, speakable requests.** Use your app's voice features or dictation. Garrick supplies the naming and reply conventions; the app supplies the microphone and voice connection.

**What the walls mean:** they are rules for the assistant, backed by limited checks before a commit. Separate folders do not create a wall automatically. A clean paraphrase can pass, and so can wording moved rather than copied from one party's note to another's. Generated Word, PowerPoint and PDF contents are outside the text scan. The hook does not block chat replies, initial file writes or sending. Review anything you intend to share. [Principles and limits](docs/principles.md#what-the-check-covers) explain the scope.

## Who it's for

People who already use Claude or Codex every day and run several lines of work at once: a few projects, partners and internal asks, put down and picked up all day. If you have one line of work, your assistant's own project memory is probably enough.

It matters most when that work holds other people's confidences: advisors, account managers, people working with partners under NDA, and members of a team who handle separate internal projects. For two internal projects to have a wall, give them separate party tags and declare the pair, even if both belong to one company.

At work, use the assistant and account your employer approves. Files stay on your disk, but content the assistant reads goes to its provider. Garrick does not control the provider's retention or training settings.

## Try the fictional workspace

On a Mac with git, Python 3.9+ and Claude Code or Codex ready:

```sh
git clone https://github.com/iamvenuti/garrick.git ~/garrick-source
cd ~/garrick-source
python3 examples/demo/build.py --target ~/Garrick-demo
```

That clone gives you `main`, the branch under development; [Desktop first steps](docs/first-steps.md) installs the newest release instead.

Open `~/Garrick-demo` in your chosen app or terminal assistant and say “what's open”. The [first-session guide](docs/first-session.md#try-the-wall-with-fictional-data) gives you a short wall demonstration. The demo builder writes only inside that target folder; your assistant keeps its own session data separately. [Try it safely](docs/try-it-safely.md) explains removal.

When you want your own, run `python3 install.py` in `~/garrick-source`. It asks one question at a time and writes into a new folder, `~/Garrick` by default. The [command reference](docs/commands.md) documents each command.

## How the files fit together

A **zone** is a side of your life, such as Work or Personal, with its own folder and git history. A **project** holds one undertaking. A **thread** is a line of work inside it, with one resume note. Meetings and Knowledge hold the source material those projects can draw on under the rules.

<details>
<summary>See the workspace diagram and optional tools</summary>

![Garrick as a shell around Claude Code or Codex, in four layers. On top, the Garrick App navigates your zones, projects and threads, and opens a thread where you work: the Claude or Codex desktop app, or cmux with a terminal tab per thread. You work on the record: Knowledge, Meetings and the work threads, each with its resume point, and mail, files and recordings are filed into it for you. Underneath, Claude or Codex is the model doing the work across the whole record. It reads the rules first, and the rules, the walls and a check on every commit apply to all of it.](docs/architecture/overview.png)

Download the [diagram page](docs/architecture/overview.html) and open it in a browser for the same drawing, in dark mode too, with a note on each layer. cmux is optional, and so are the ways in.

</details>

## Core and extras

Garrick is the installer, workspace template, rules, skills and Python tools. It needs git, Python and an assistant that can read and edit local files and run the tools. The core has no desktop app; the Garrick App is one of the extras.

[Extras](docs/extras/index.md) include Obsidian, cmux, a meeting recorder, mail fetching, phone access, scheduled jobs and the Garrick App, which shows where every thread stands, on the Mac or in a browser. Add one when it solves a problem you have; none is required for the first session.

## Status and documentation

Early, for macOS, and built from one person's working week. See the [changelog](CHANGELOG.md).

- [Desktop first steps](docs/first-steps.md) and [terminal setup](docs/terminal-setup.md).
- [Your first useful session](docs/first-session.md) and [guided setup](docs/guided-session.md).
- [Command reference](docs/commands.md), [principles and limits](docs/principles.md), and [assistant compatibility](docs/harnesses.md).
- [Concepts](docs/concepts.md), the words Garrick uses; [architecture](docs/architecture.md), how the parts fit together; [how Garrick keeps context](docs/context.md); and [what is enforced, and what is asked](docs/enforced.md).
- [Updating to a newer Garrick](docs/updating.md), keeping what you changed.
- [The demo workspace](examples/demo/README.md) and [the introduction](presentation/index.html) (open it in a browser from your downloaded copy, which holds its images).

## Contributing

Ask questions and give feedback in [Discussions](https://github.com/iamvenuti/garrick/discussions).

Issues and ideas are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first. Report a bypass of a documented check through [SECURITY.md](SECURITY.md), using fictional data.

## Licence

MIT. See [LICENSE](LICENSE).
