# Guided session

Set up Garrick with someone beside you, then use it on one real piece of work. You share your screen and drive. Allow up to two hours, with a shorter follow-up two to three weeks later.

By the end, you should have one conversation filed, a useful brief, and a next action that a fresh chat can recover. You will also see a declared wall applied in the fictional demo.

## Before the call

Follow [Desktop first steps](first-steps.md) through preparing your Mac and choosing an assistant. Download Garrick, but leave its installation for the session if you want help with the questions. Someone comfortable in Terminal can use [Terminal setup](terminal-setup.md) instead. Both routes produce the same workspace.

Bring:

- One project you want to pick up tomorrow, and the question you need answered.
- One short email, transcript or typed call note you are allowed to use with your chosen assistant and account.
- The names of the parties involved. A party can be a client, partner or confidential internal project.
- Any pair whose information must stay apart. Start with the parties relevant to this project; you can add others later.

The facilitator will help with unfamiliar terms. You do not need to prepare a complete map of your work, install Obsidian or cmux, or connect your mail account.

## In the session

1. **See a brief and a wall.** Try the fictional workspace for a few minutes. See what it should hold back and hear the limits of the checks.
2. **Install your workspace.** Name the first parties and the boundaries between them. Select your new folder in the app, or open your terminal assistant there.
3. **Use your own material.** Follow [Your first useful session](first-session.md): file the conversation, check its labels and produce a brief for your project.
4. **Save and return.** Tell the assistant the next action, say “wrap it”, then open a fresh chat and ask where you stand.
5. **Check it together.** Ask the assistant to run the workspace check and explain any finding. Review the brief before sharing it.

Confirm which app, folder and prompt you will use tomorrow. Add phone access only after this works at the desk.

## What gets installed

Garrick creates a folder containing your notes, rules, skills and local git history. Nothing is connected to your mailbox or recorder, and nothing runs on a schedule. Your chosen assistant supplies the app or terminal interface and processes the material it reads through its provider.

Declared walls guide the assistant. The commit hook checks supported text for certain names, links and copied wording; it cannot guarantee confidentiality. Read [what the check covers](principles.md#what-the-check-covers) together before using real confidential material.

## Between sessions

Return to the project for a real task, then wrap it. Try filing one more conversation yourself. Note where you needed help or where the result was not useful, and bring the notes to the follow-up. If something breaks and stops you before then, tell your facilitator straight away, and describe it without client names or content. Include the line `python3 System/tools/check.py --version` prints in your workspace: it says which Garrick you have, so the facilitator knows whether the problem is already fixed. If you never returned, that is useful feedback too.

## The follow-up

Two to three weeks later, start by opening your project in a fresh chat. Review what you actually used, whether the brief was accurate, and how much help each step needed. Then repeat one filing and brief without the facilitator directing you.

Add an [extra](extras/index.md) only to address a need you encountered: browsing in Obsidian, several terminal sessions in cmux, mail intake or [phone access](extras/phone-access.md). The files and resume notes stay the same whichever interface you choose.
