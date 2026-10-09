---
name: setup
description: >
  The first run in a new workspace: find out what this Mac has and how the
  user works, write it down so every later session knows, fix what is
  missing on a yes, then hand over to the interview or fill in the resume
  points of the projects already here. Use when the user says "set up
  Garrick", "first run", "get me started", "check my setup", "what do you
  know about my setup", "I've installed Obsidian" (or cmux, or another
  assistant), or "fill in my resume points", and when the check reports a
  thread with no real resume point yet.
---

# Setup

Garrick was built on one person's Mac, and a new one is never the same: a
different assistant, the app or the terminal, cmux or not, Obsidian or not.
This skill looks before it assumes. It finds what is installed, asks only what
it cannot find, and writes the answer to `System/setup.md`, so the next
session starts knowing how this user works instead of guessing.

Everything here works spoken or typed, one question per turn, as *Listening
mode* in the `threads` skill describes.

## Where things are

| What | Path |
|---|---|
| What this Mac has | `python3 System/tools/probe.py`. Read-only; sends nothing |
| How the user works, written by this skill | `System/setup.md` |
| Who the user is and who they deal with | `System/context.md`, the `interview` skill's job, not this one's |
| Resume points not filled in yet | `python3 System/tools/check.py --json`, findings in the `resume` check that say "still the template's" |

## "Set up Garrick"

1. **Look.** Run `python3 System/tools/probe.py` and read what it found. You
   already know which assistant you are, and whether you run in a desktop app
   or a terminal: don't ask that.
2. **Say it back in one or two sentences**, and only what matters for
   working here. Spoken: "You're in the Claude app, with Obsidian and cmux
   installed, and git saves your history under your own name. Right?"
3. **Ask what the probe cannot know**, one per turn, and skip any the user
   has already answered:
   - "Will you mostly type, dictate, or talk and listen?" Listening means
     every reply comes in its spoken form.
   - Only if Obsidian is installed: "Do you want to browse your notes in
     Obsidian?" A yes means the workspace folder is opened as a vault: say
     how (Obsidian, *Open folder as vault*, the workspace folder), never do
     it for them.
   - Only if there is more than one assistant or app: "Which one will you
     use day to day?"
   - Only if Claude Code runs in a terminal: "Do you want the Garrick band,
     the thread you're in and where it stands, above the prompt?" A yes
     means loading the mod in `extras/mods/garrick-band/` of the Garrick
     download: say how, from its README, never change the settings for them.
   - Only if the assistant is Claude Code or Codex: "Do you want me to stop
     and check with you before I change a file outside the project you
     opened me in?" A yes means the zone guard in `extras/hooks/` of the
     Garrick download: say how, from its README, never change the settings
     for them.
4. **Write `System/setup.md`**, or rewrite it if it exists, re-reading it
   first. Facts only, in this shape, and nothing about the user's work or
   parties: that belongs in `System/context.md`.
   ```markdown
   # How I work here

   Checked <D Month YYYY> by the setup skill. Say "check my setup" after installing or removing a tool.

   - **Assistant**: <assistant>, in <its desktop app | a terminal>.
   - **Replies**: <typed | spoken first, for listening>.
   - **Installed**: <what the probe found that Garrick can use: cmux, Obsidian, gh, the other assistant>.
   - **Not installed**: <what Garrick would use but is absent>. Never suggest a step that needs one of these; name the extra that adds it if it would help.
   - **Notes in Obsidian**: <yes, the workspace is a vault | no>.
   ```
   Commit it alone in the workspace's own repository:
   `git add -- System/setup.md && git commit -m "Setup: how I work here"`.
5. **Fix what is missing, on a yes, one at a time:**
   - *git has no name or address*: saving history fails. Ask for the name
     and address to use, and set them in each repository with the command in
     `docs/getting-started.md`, or `git config user.name` and
     `user.email` per repository.
   - *git skips the wall check* somewhere: run
     `git config core.hooksPath .git/hooks` in each repository named, after
     saying what it does.
   - Anything else the probe flagged: say what it means, and what it would
     take, then leave it unless the user asks.
6. **Hand over.** Read `System/context.md` and list the projects:
   - No parties and no projects yet: "Next, I'd like to ask you about your
     work, one question at a time. Say 'interview me' when you're ready."
   - Projects whose resume points are still the template's: offer the next
     section. "Three of your threads have no real resume point yet. Shall we
     fill them in? It takes a minute each."
   - Otherwise: "You're set up. Say 'what's open' to see your work."

## "Fill in my resume points"

A thread made from the template, or brought in from another folder, starts
with prompts in angle brackets where its resume point should be. The status
page and every cold resume trust that block, so a prompt left there is worse
than nothing: it looks like an answer.

1. **Find them**: `python3 System/tools/check.py --json`, the `resume`
   findings that say "still the template's". One thread at a time, most
   recently changed first.
2. **Ask four things**, one per turn, in plain words, and skip what the
   user already said:
   - "Where does <Thread> stand?"
   - "What's the next thing to do on it, and whose is it?"
   - "Are you waiting on anyone?"
   - "Is there a deadline?"
   The live artifact and how to rebuild it: read the thread's folder and
   propose them ("the live file looks like `Deliverables/<file>`; right?"),
   rather than asking.
3. **Write it** as the `threads` skill's *Wrap* does: rewrite the Resume
   here block with the answers, add today's dated entry below it, and commit
   in the zone as that procedure says. Never invent an answer the user didn't
   give: write "none" or "not set" where they said so, and leave the prompt
   where they skipped.
4. After each one: "Next is <Thread>. Or stop here?" Stop whenever the user
   says so.

## Never

- Never install, download, sign in to or configure an app for the user.
  Say what it would take and leave it.
- Never write the user's work, parties or anything said in confidence into
  `System/setup.md`.
- Never change a git setting, a resume point or any other file without the
  yes this skill asks for.
- Never send anything off the machine. The probe and this skill only look.
