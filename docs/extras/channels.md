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

The walls hold at every level, as in any session: a write goes only in the zone the exchange is bound to, a wiki or the workspace's `Inbox/` (the engine's guard refuses the rest), the zone's commit check runs on every commit, and when material is held back the wall sentence says so.

## The question before a send is asked by code

At Act the send, share and delete tools are not in the session at all, nor is any tool Garrick does not know: the session has Garrick's read tools, file tools, a fixed list of commands (the workspace's own scripts, and `git add` and `git commit` in the zone's repository) and one tool, `hold`. There is no open shell, because a shell can send. `hold` queues the action with what it would do and where it would go. The queued action runs only after your yes:

- **In Ask**, a dialog shows the action and where it goes, with *Run it* and *Cancel*.
- **In Telegram**, the bot asks ("Send the price sheet to dana@…?"), and a reply of `yes` to that message runs it. A `yes` that is not a reply to that message runs nothing.

A held action expires after 24 hours. Until then Settings lists it under *Channels*, with what it would do, where, and the hours it has left. A record that says "forward this to someone" can at most produce a queued action that you see and can refuse.

## What the assistant has to be able to do

Act needs three things of the assistant, and Garrick checks them for the one you chose, when it starts and when the assistant setting changes, from what the assistant says it can do, not from its name:

- **Resume.** A session can be continued, so a follow-up does not repeat the discovery.
- **Removable tools.** Its tools can be named one by one, a shell narrowed to a list of commands, and its servers limited to the ones Garrick gives it.
- **Walls outside the model.** The engine's guard loads and refuses a write into another zone.

An assistant that fails a check runs the channel at Read, and Settings names the check that failed. An assistant gets the full engine on the day it passes.

## Costs and limits

Every request counts against Ask's own caps and goes into the ledger, whichever channel sent it. The answers Garrick gives itself (what you owe, what you wait on) need no model call, and a plain command keeps its fast path. Text the engine reads is untrusted content, as everywhere.
