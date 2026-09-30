# Guided session

A guided session is Garrick installed with someone beside you. You share your screen, you type, and the facilitator explains what each question means. It suits people who don't use a terminal day to day. It takes two hours, with a shorter follow-up two to three weeks later.

## Before the call

Fill in this worksheet beforehand, so the two hours aren't spent thinking up answers. It covers what `install.py` will ask:

- Your name, and one line on what you do and for whom.
- The parts of your life or work that should never mix by default. Most people settle on two, such as Work and Personal. These become your zones.
- Every organisation or person whose confidences you hold: what it is, which zone it belongs to, a one-word tag, and the domain their email comes from, if you know it.
- Any pairs of those whose material must never meet, and why. These become your walls.
- People you deal with regularly, so their names get recognised instead of guessed at.
- Names your phone or dictation tends to mangle, if you already know any.
- Your first real project: its name, which party it's for, and the name of its first line of work. Pick names you can say aloud, without digits or dates.

Check that you have, before the call ([First steps](first-steps.md) sets each one up):

- a Mac with Python 3.9 or later (`python3 --version` in Terminal);
- git (`git --version`). If it's missing, run `xcode-select --install` a day ahead: it takes a while and needs nothing from you once started;
- the Claude desktop app with its Code tab, or Claude Code in Terminal (`claude --version`, 2.1.277 or later), or Codex, installed and signed in, with Help improve Claude turned off in Claude's privacy settings;
- a copy of Garrick, downloaded as a ZIP from the repository page and unzipped, or cloned with git. Note where it landed.

## In the session

- **The model.** Zones, projects, threads, one memory with walled use, and one resume point per thread. [Principles](principles.md) covers the same ground if you want to read ahead.
- **The install.** You run `python3 install.py` and answer each question yourself, with the worksheet open beside it.
- **A tour.** `AGENTS.md`, then `System/rules.md`, then `System/context.md`, now filled in with your own zones and parties.
- **Your first project.** Your own first client or undertaking, not an invented one, created by asking the assistant in plain language.
- **Open and wrap.** You open a thread, tell the assistant where the work stands, wrap it, and hear it read back. This is the habit everything else depends on.
- **The check.** `python3 System/tools/check.py`: a clean pass, a problem made on purpose, and a clean pass again.
- **The two memories.** Where a transcript or an email goes to be filed later.

## What gets installed

Exactly what `install.py` produces and nothing more: the workspace in the folder you chose, with `AGENTS.md`, `System/` (the rules, your context, the tools and skills), empty Meetings and Knowledge wikis, and one folder per zone, each its own git repository. Nothing is set up in Obsidian, no recorder or mail account is connected, and nothing runs on a schedule. Those are the [extras](extras/index.md). You can add any of them later, and the workspace doesn't need them to work.

## The follow-up

Two to three weeks later, bring at least one real conversation: a transcript exported as text into `Wikis/Meetings/raw/inbox/`, or an email saved as a `.eml` file into a zone's `Inbox/`. In the follow-up you:

- file it into the Meetings memory, answering the one-line questions about zone and parties yourself. That answer is where a wall gets set;
- test a wall on purpose, and see the assistant refuse to carry one party's material into another party's project, while still answering a plain question about it outside any project;
- run the check again to see whether anything drifted.

Nothing breaks if you don't touch the workspace between the two sessions.
