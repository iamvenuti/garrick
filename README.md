# Garrick

[![Tests](https://github.com/iamvenuti/garrick/actions/workflows/tests.yml/badge.svg)](https://github.com/iamvenuti/garrick/actions/workflows/tests.yml) [![MIT licence](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE) ![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

**The layer under your agent harness: plain folders on your own disk become the one place your work and your memory live.**

An operating system for knowledge work, run by the AI assistant you already use.

You've let AI into your code. Your client work still lives in chat tabs, a notes app and your head.

Garrick puts it in plain folders on your own disk, and gives any assistant the rules to run them.

[![Asked to prep for a meeting with a supplier both clients use, the assistant checks the wall between them and leaves the other client's call out of the brief.](docs/assets/demo-wall.gif)](https://github.com/iamvenuti/garrick/releases/download/v0.1.0/garrick-launch-video.mp4)

*The wall at work: two walled clients, one shared supplier, and a brief that holds back what the other client said. [Watch the 84-second video](https://github.com/iamvenuti/garrick/releases/download/v0.1.0/garrick-launch-video.mp4) (with [captions](https://github.com/iamvenuti/garrick/releases/download/v0.1.0/garrick-launch-video.srt)).*

- **Walls between clients.** Every conversation goes into one memory, because that is how you hold them. Walls you declare decide where that memory may be used, and a check before every commit stops one client's names, or words lifted from its meetings, reaching another client's work.
- **Any assistant.** Claude Code or Codex today. The rules are files in the workspace, not settings in one vendor's app, so switching costs you nothing.
- **Built to be spoken to.** Open a thread, file a meeting, close the day, by voice. Names are ones you can say aloud, and short answers come back when you're listening.
- **Yours.** Markdown under git. Try it in a folder you can delete; your existing setup stays as it is.

![Garrick at a glance: mail, recordings and files come in; your assistant files them into the Meetings and Knowledge memories or a client project, following the rules; you talk to it in cmux or on your phone, and browse everything in Obsidian.](docs/architecture/overview.png)

An [interactive version](docs/architecture/overview.html) walks through it step by step; download it and open it in a browser.

## Try it

On a Mac with git and Claude Code or Codex (new to Terminal? [First steps](docs/first-steps.md) sets your Mac up in about 30 minutes):

```sh
git clone https://github.com/iamvenuti/garrick.git
cd garrick
python3 examples/demo/build.py --target ~/Garrick-demo
```

That builds an invented advisor's workspace, four weeks into use. Start Claude Code or Codex in `~/Garrick-demo` and say "what's open". Nothing is written outside that folder, so deleting it removes the lot ([try it safely](docs/try-it-safely.md) has the details).

When you want your own:

```sh
python3 install.py
```

It asks one question at a time and writes only into the folder you name (`~/Garrick` by default). [Getting started](docs/getting-started.md) walks through it.

## How it is organised

- **Zones** for the separate sides of your life, such as work and personal. Each is its own folder and its own git repository.
- **Projects** inside a zone: one per client or undertaking.
- **Threads** inside a project: one per line of work, each with a single "resume here" point, so you can say "open Acme pricing" and hear where you left off.
- **Two memories**: Meetings, for every conversation, including correspondence, and Knowledge, for the published material you study. Mail and files dropped in a zone's inbox are filed where they belong: a conversation into Meetings with its parties, so the walls see it too; a newsletter into Knowledge; a client's document into its project, after the wall check.

Dictation mistakes in names get matched against your own list of names, so a mangled client name still lands in the right project.

## Core and extras

Core is the installer, `install.py`, and everything it copies from `template/`: the folder structure, the rules and context files, the scaffold and check scripts, and the skills. Core never depends on anything outside itself.

Extras are tools that add value but aren't part of Garrick: Obsidian as a reader, cmux for one terminal tab per thread, a recorder such as Plaud feeding the meetings inbox, your assistant's mail connector, an IMAP script or a mail rule fetching mail into a zone's inbox, phone access through an assistant's remote features, scheduled jobs. Each is documented in [`docs/extras/`](docs/extras/index.md), with what it adds and what you lose without it, which in every case is nothing that core needs.

## Status

Early. You need macOS, Python 3.9 or later and git (both come with the Command Line Tools: `xcode-select --install`), and Claude Code or Codex. What changed between releases is in the [changelog](CHANGELOG.md).

## Documentation

- [The demo workspace](examples/demo/README.md): an invented advisor's month, and the shot list for the three-minute voice demo.
- [The introduction](presentation/index.html): fifteen slides on the idea and its rules. Open it in a browser; arrow keys move, N shows the speaker notes.
- [First steps](docs/first-steps.md): for anyone new to Terminal. Git and Python, the Claude desktop app and the settings it needs for private work, Obsidian, dictation, and Gmail routing with plus addresses and a filter.
- [Getting started](docs/getting-started.md): install, your first project, opening and wrapping a thread, the check.
- [Principles](docs/principles.md): what the workspace actually is, and why it's built the way it is.
- [Try it safely](docs/try-it-safely.md): install into a throwaway folder, see exactly what it does and doesn't touch, remove it in one command.
- [Claude Code and Codex](docs/harnesses.md): what each reads, and why each zone is its own git repository.
- [Extras](docs/extras/index.md): the tools that pair well with Garrick but aren't part of it.
- [Guided session](docs/guided-session.md): what happens when someone installs it with you, and what to prepare.

## Contributing

Issues and ideas are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first, because of the clean-room rule. A way through the walls is a security report, not an issue: see [SECURITY.md](SECURITY.md).

## Licence

MIT. See [LICENSE](LICENSE).
