# Telegram: one private chat for your work threads

Ask about a piece of work, answer a question the assistant asked, or drop a thought for later, from your phone, with your desktop closed. One private chat with your own bot serves every thread. Everything here is optional, and Garrick works without it.

Garrick's receiver is a small always-on program on your Mac. It listens to the bot, sorts each message by code (no model decides where a message goes), saves it, and calls the assistant only when there is work. Idle, it makes no assistant call.

## What you can send

- **A note.** A message that starts with `note` or `note:` is saved as a [note to yourself](ways-in.md#notes-to-yourself) and never reaches the assistant: `note for Acme pricing: Dana hinted the floor could move`. The bot replies *Noted.* and the hourly [notes job](scheduled-jobs.md#notes-processed-hourly) files it.
- **A question or a request.** Name the thread, or just carry on. A message that names a thread binds to it ("Acme pricing: where do we stand?"). A message that names none continues the thread you were last talking about, while that conversation is still open. With none open, the bot asks *Which thread?*. When a name could mean two threads, it asks one short question before it reads or changes anything, and lists up to three places it could mean. Reply to the question, or type the answer as a new message within ten minutes: either one answers it, and your first question is the one the bot then answers. A typed message counts as the answer only when it is a plain *yes* or *ok*, names a place the question listed, or names no place at all; a message that names another place by itself is a new request. An answer typed later than ten minutes after the question is a new request too. A project's one *active* thread is the one the bot takes for a project name; parked and finished threads are not counted. A project name alone is enough for a question: the bot answers from the project's Resume block and its threads' next actions. A later message that names one of its threads narrows the conversation to that thread. Only a note must name a thread.
- **A reply.** A reply to one of the bot's messages always continues the conversation that message belongs to, whatever its first word and even after you talked about something else since.
- **`deep:`** at the start of a message runs that one request on the large model at high effort. Your settings do not change.
- **`done`** saves the conversation and closes it.

Every reply opens with its thread's name, so a wrong guess shows at once. Text only for now: a voice file or a photo is not read. Dictate on your phone and send the text.

## How far it may go

The Telegram channel has its own tier, effort and autonomy in Settings under *Channels* (see [Channels](channels.md)). The default is Act: it edits notes, files, ticks and commits, since git can undo each. A send, share or delete is held, and the bot asks in the chat: *Send the price sheet (dana@example.com)? [tool send_message; to: dana@example.com] Reply yes to run it, or no to cancel it.* The part in brackets is added by code from the action itself, not written by the assistant. Reply `yes` **to that message**, and it runs. A `yes` that is not a reply to that message runs nothing. Reply `no`, `cancel` or `stop` (alone, in any case) **to that message**, and the action is cancelled at once: it leaves the held list, the bot says nothing was done, and a later `yes` to the same message runs nothing. A `no` that is not a reply to that message cancels nothing. Telegram never offers Full.

## Conversations, sessions and the two-hour limit

Each conversation about one thread keeps one assistant session, so a second message an hour later resumes it instead of starting the discovery again. A session lasts at most **two hours from when it began** (a maximum age, not an idle timer; a resumed turn that comes back with another session id does not restart the count), and ends earlier if its measured input passes **120,000 tokens**. Garrick checks both between turns, by the clock, with no assistant call. A turn that fails also ends its session, so the next message starts fresh instead of resuming a broken one. A message that cannot be read gets one line (*I could not read that; send it again.*), and one saved but not yet decided when Garrick restarted is decided again once. A new message after that starts a new session from what Garrick saved: the thread's own resume point, the question waiting on you, and the last few turns, each cut short. It never replays the chat, so the same question after a hundred unrelated messages reads none of them. Decisions live in your notes; what is saved besides is the thread it is bound to, the questions waiting, the message ids and when each session began and ended, in a file in the jobs folder, outside your workspace.

A burst of messages for one conversation is batched: ten seconds after the last one, or thirty after the first at most. Messages for different conversations stay apart, and a request already running queues its follow-ups.

A retained session saves setup, not tokens as such: the receiver records the input and cost of each first and resumed turn so the two can be compared.

## Set it up

1. **Make a bot** with Telegram's BotFather and keep its token. Store it in the Keychain, typing it at the prompt so it never appears in a command line: `security add-generic-password -s garrick-telegram -a bot -w`
2. **Retire any other program that reads this bot.** Two programs confirming updates for one bot lose messages to each other, and Telegram reports a conflict only for a webhook or two concurrent long polls, so Garrick checks for itself: it asks for a webhook, and reads the pending updates twice a few seconds apart, and if they vanish without Garrick confirming them, another poller is running. If either is found, the receiver does not start, setup says which, and the status page shows it. A poller of your own for the same bot is replaced by this receiver, which also takes over capturing notes.
3. **Run setup**: `/usr/bin/python3 extras/fetch/telegram_receiver.py setup --config ~/.config/garrick/telegram.json --workspace ~/Garrick`. It states the exposure below, asks you to accept it, runs the check above, and pairs your private chat: you send the one-time code it prints to the bot. Use `/usr/bin/python3`, the Python the service runs: it trusts the macOS Keychain, so a chat that pairs also runs. The config holds your chat's id, readable by you only.
4. **Load the service**: copy `extras/jobs/launchd/garrick.gr-telegram.plist` to `~/Library/LaunchAgents/`, edit its paths, and `launchctl bootstrap` it. It starts at login and restarts after a crash. Settings under *Channels* shows whether it is running and when it last heard from you.

**What you accept.** Bot chats on Telegram are not end-to-end encrypted. Every zone may answer in full once the channel is on, so an answer from a walled zone is held on Telegram's servers. Pairing your chat is your acceptance.

## Working beside your desk

An open desktop session does not stop remote questions or notes, and the receiver never types into a live session. A remote change is made by an assistant session that re-reads a file right before it edits, leaves a file with changes you have not committed alone and says so, and commits only the files it changed, by name. A note filed from the chat is a new file, so it never collides with your edits.

## What stays out of reach

The receiver accepts messages only from your private chat with the bot: another sender, a group or a channel is ignored and nothing of it is kept. Code sends every reply, to that chat only, and refuses any other destination. The assistant has no tool that sends to Telegram, and text in a message cannot name a destination or widen what it may do. The assistant works only in the zone a conversation is bound to, and a write outside it is refused.

If the assistant is busy or a limit is reached, the request waits with a short explanation and is not retried on its own. After a restart, a request that was running is not run again (what it committed is saved): you are told once. A reply that could not be confirmed as sent is recorded as uncertain, and the work that made it is never run again for that.
