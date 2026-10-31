---
name: setup
description: >
  The first run in a new workspace: find out what this Mac has and how the
  user works, write it down so every later session knows, fix what is
  missing on a yes, then hand over to the interview or fill in the resume
  points of the projects already here. Use when the user says "set up
  Garrick", "first run", "get me started", "check my setup", "what do you
  know about my setup", "I've installed Obsidian" (or cmux, or another
  assistant), "fill in my resume points", "add a rule", "make that a
  rule", "set up notifications" or "tell me when a session needs me", and
  when the check reports a thread with no real resume point yet.
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
| The user's own rules, which win over Garrick's | `System/rules.local.md` |
| A zone's or a wiki's own routing | `AGENTS.local.md`, beside its `AGENTS.md` |
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
   - Only if the assistant is Claude Code and the probe found no commands
     allowed here: "Shall I run Garrick's own tools, and git's status, diff,
     log, add and commit inside the workspace, without asking you each time?
     None of them sends anything off your Mac." A yes means
     `python3 install.py --allowlist <this workspace>`, run from the Garrick
     download, which writes the rules the installer would have written: say
     how, never change the settings for them. Once they have run it, commit
     the two files it wrote, `.claude/settings.json` and
     `System/garrick-settings.json`, in the workspace's own repository.
   - Only if the assistant is Claude Code or Codex, and
     `python3 System/tools/notifications.py hooks` does not already say
     "on" for it: "Do you want a notice when a session needs you, or has
     finished a long turn?" A yes means running
     `python3 System/tools/notifications.py hooks --install`, which adds
     Garrick's hooks to the assistant's own settings in your home folder and
     keeps every hook already there; `--uninstall` takes them out. For
     Codex, then say to run `/hooks` in Codex and trust them. Notices go to
     this Mac, or to a session's own tab in cmux; which ones, and quiet
     hours, are the status page's Settings › Notifications: say so, and
     change nothing there.
   - Only if the cmux extra is here (`System/cmux/desk.py`) and
     `System/desk.json` does not already set `agent`: which assistant a cmux
     tab starts. The probe found the `codex` command and
     not `claude`: run `python3 System/cmux/desk.py agent codex`, and say
     so. `claude` and not `codex`: `python3 System/cmux/desk.py agent claude`.
     Both: "Should a cmux tab start Claude Code or Codex?", then run it with
     the answer. Neither: leave it. It writes `agent` in `System/desk.json`,
     the same choice as Settings › Opening a thread in the Garrick App.
   - Unless `System/garrick-settings.json` already says: "Tell me when a new
     Garrick is out? It asks GitHub once a day and sends nothing about your
     workspace." Ask it once. A yes or a no is written as the `update`
     skill's *Tell me when a new Garrick is out* says, `true` or `false`,
     so the question is not asked again.
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
   - **Told of a new Garrick**: <yes, once a day | no>.
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
6. **Offer the Mac app**, as the last question before you hand over, and
   only where `System/garrick-settings.json` says `"home": "simple"`,
   `System/status/app/make-app.sh` is there, this is a Mac, and
   `~/Applications/Garrick.app` is not there yet. The simple home is the
   status page: the installer put it in `System/status/` and built it once,
   and the app that shows it in a window of its own is built here, on a yes.
   Ask in one plain sentence: "Shall I make your Garrick home an app on this
   Mac, so it opens from the Dock like any other?" On a yes, say "Making the
   Garrick app now; it takes a minute", then run, from the workspace,
   `System/status/app/make-app.sh --workspace "<this workspace>"`. It
   compiles the app with the Xcode command line tools, downloads nothing,
   and puts it in `~/Applications`, printing its place as its last line.
   Then: "It's in your Applications folder as Garrick. Drag it to the Dock
   to keep it there." If it fails, say what its last line means in plain
   words, and that the home still opens in a browser from
   `System/generated/status.html`. On a no, leave it there.
7. **Hand over.** Read `System/context.md` and list the projects:
   - No parties and no projects yet: offer the short way first, and the
     interview as the fuller one. "Tell me one thing you need to prepare,
     and I'll set up just enough to do it. Or say 'interview me' and I'll
     ask about your work first, one question at a time." The short way is
     the `meetings` skill's *Nothing there yet*, which asks one question and
     leaves a brief in a thread note; the `interview` skill is the twenty
     minutes that sets up the whole workspace first, and is unchanged.
   - Projects whose resume points are still the template's: offer the next
     section. "Three of your threads have no real resume point yet. Shall we
     fill them in? It takes a minute each."
   - Otherwise: "You're set up. Say 'what's open' to see your work."

## "Set up notifications"

Ask the notification question from step 3 of *Set up Garrick*, alone, and
act on the answer as it says. Then say where the rest is chosen: the status
page's Settings › Notifications, in the Mac app or Obsidian. Without the
status page, notices go to this Mac until `notifications` in
`System/garrick-settings.json` says otherwise; the status page's docs say
how it reads.

## "Add a rule", "make that a rule"

A rule of the user's own, such as "always answer in Italian" or "never book
a meeting before ten", goes in `System/rules.local.md`, never in
`System/rules.md`: that file and every `AGENTS.md` are Garrick's, and an
update replaces them as shipped. The local file adds to Garrick's and wins
where the two differ.

1. **Say the rule back** in one sentence, in the user's words, and where it
   goes: "I'll add: answer in Italian, under Talking to me. Right?"
2. **On a yes, write it.** Re-read `System/rules.local.md`, then add the rule
   as one line under the heading it would have in `System/rules.md`, such as
   `## Talking to me` or `## Autonomy`, adding the heading when the file
   lacks it. A rule that overrides one of Garrick's names it: "Instead of
   Garrick's twenty-minute estimates: give a range." If the file is missing,
   start it with `# Your rules` and one line saying it adds to `rules.md`.
3. **Routing for one zone or wiki**, such as "questions about invoices go to
   the Money project", goes in that folder's `AGENTS.local.md` instead, made
   the same way, and pointed to by the `AGENTS.md` beside it already.
4. **Commit it alone** in the repository that holds it:
   `git add -- System/rules.local.md && git commit -m "Rules: <the rule, short>"`.

## "Fill in my resume points"

A thread made from the template, or brought in from another folder, starts
with prompts in angle brackets where its resume point should be. The status
page and every cold resume trust that block, so a prompt left there is worse
than nothing: it looks like an answer.

1. **Find them**: `python3 System/tools/check.py --json`, the `resume`
   findings that say "still the template's". One thread at a time, most
   recently changed first.
2. **Ask five things**, one per turn, in plain words, and skip what the
   user already said:
   - "Where does <Thread> stand?"
   - "What's the next thing to do on it, and whose is it?" If the answer
     would take more than two minutes to start, ask for the first step of it.
   - "Are you waiting on anyone?"
   - "Is there a deadline?"
   - "Anything about it that's only in your head?" (the *Keep in mind* row;
     "nothing" is a fine answer)
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
  Say what it would take and leave it. The notification hooks and the
  Garrick app, built on this Mac from the workspace's own `System/status/`,
  are the two exceptions, and each only on the yes its question asks for.
- Never write the user's work, parties or anything said in confidence into
  `System/setup.md`.
- Never edit `System/rules.md` or an `AGENTS.md`: the user's rules and
  routing go in the `.local.md` file beside it.
- Never change a git setting, a resume point or any other file without the
  yes this skill asks for.
- Never send anything off the machine. The probe and this skill only look,
  and a test notice is sent from the status page, by the user.
  Switching on the release notice is the user's yes to one request a day
  to GitHub, made later by the status page, never by this skill.
