# Channels: how far a request may go

The Ask box and the [Telegram channel](telegram.md) answer you, and can do work for you. Both run through one engine, and each channel has three settings, in Settings under *Channels* (kept in `System/garrick-settings.json` as `channels.ask` and `channels.telegram`):

| Setting | Values | Default, both channels |
|---|---|---|
| Model size (tier) | small (`haiku`), medium (`sonnet`), large (`opus`): a tier, never a model name | medium. A plain "open Pricing" or "park Pricing" stays on small |
| Effort | low, medium, high | medium |
| How far it may go (autonomy) | Read, Act, Full | Act |

Start a message with `deep:` and that one request runs on the large model at high effort. Your settings do not change. Garrick's code finds the word; no model decides it.

## The three levels

They follow the *Autonomy* section of `System/rules.md`.

- **Read.** It answers and proposes. Nothing is changed.
- **Act.** It does what git can undo without asking: it edits notes, files the inbox, ticks and adds Todo lines, makes and moves threads, and commits. Before anything that leaves the machine or cannot be undone (sending, sharing, deleting, writing to a synced shared folder, rewriting history) it asks you first.
- **Full.** Act, and it also sends without asking. Offered for Ask only. Telegram never offers Full: nobody is at the desk to stop a wrong send, and an unlocked phone should not be enough to send mail in your name. Settings refuses it for Telegram, and a file edited by hand to say so is read as Read.

An updated workspace gets the defaults: Ask at Act. Telegram stays off until you [set it up](telegram.md).

The walls hold at every level, as in any session: a write goes only in the zone the exchange is bound to, a wiki's `wiki/` folder (never its `raw/` record, except the Meetings inbox) or the workspace's `Inbox/`, and never into a `.git` folder or a `.gitattributes` or `.gitmodules` file (the engine's guard refuses the rest, and exits with the code that makes Claude block), the zone's commit check runs on every commit, and when material is held back the wall sentence says so.

## The question before a send is asked by code

At Act the send, share and delete tools are not in the session at all, nor is any tool Garrick does not know: the session has Garrick's read tools, file tools, a fixed list of commands and one tool, `hold`. There is no open shell, because a shell can send. Every command is one call of a wrapper that checks each argument against the zone the exchange is bound to, and nothing may be joined to it (no pipe, redirect or second command). The list: `git add` (named files only), `git commit` (with `-m`; never `-a`, `--amend`, `-n` or `--no-verify`), `git status`, `git diff` and `git log` in the zone's repository; the intake commands `parse`, `file-conversation`, `file-reading`, `file-to-project`, `extract-attachment`, `move-to-zone`, `skip`, `file-note` and `notes`, with files taken from the zone's `Inbox/` and projects inside the zone; `scaffold project`, `thread` and `checkpoint` for the zone only; `check --quick`; and the todo digest for the zone. `intake list` (it returns every zone's inbox), `process-notes`, `learn` and every other command are not offered. `hold` queues the action with what it would do and where it would go. It accepts only a connector tool named `mcp__<server>__<tool>` that sends, shares or deletes. The confirmation shows, rendered by code and beside the assistant's own words, the tool's name and the arguments that say who it reaches (`to`, `cc`, `bcc`, `recipients`, `attendees`, `email`, a share target or a path). The queued action runs only after your yes, and runs once however many times you say it:

- **In Ask**, a dialog shows the action and where it goes, with *Run it* and *Cancel*.
- **In Telegram**, the bot asks ("Send the price sheet to dana@…?"), and a reply of `yes` to that message runs it. A `yes` that is not a reply to that message runs nothing.

A held action expires after 24 hours. Until then Settings lists it under *Channels*, with what it would do, where, and the hours it has left. A record that says "forward this to someone" can at most produce a queued action that you see and can refuse.

## What the assistant has to be able to do

Act needs three things of the assistant, and Garrick checks them for the one you chose, when it starts and when the assistant setting changes, from what the assistant says it can do, not from its name:

- **Resume.** A session can be continued, so a follow-up does not repeat the discovery.
- **Removable tools.** Its tools can be named one by one, a shell narrowed to a list of commands, and its servers limited to the ones Garrick gives it.
- **Walls outside the model.** The engine's guard loads, and its own command line, run once as a session runs it, stops a write outside the zone with the exit code Claude blocks on.

An assistant that fails a check runs the channel at Read, and Settings names the check that failed. An assistant gets the full engine on the day it passes.

## Costs and limits

Every request counts against Ask's own caps and goes into the ledger, whichever channel sent it. The answers Garrick gives itself (what you owe, what you wait on) need no model call, and a plain command keeps its fast path. Text the engine reads is untrusted content, as everywhere.
