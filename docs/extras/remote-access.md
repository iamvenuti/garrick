# Extra: remote access (preview)

Remote access lets an assistant on your phone, or on another computer, work with your workspace over a remote connection. It can read a thread, answer follow-up questions, and save a note or an action, by voice where the assistant supports voice. The workspace stays on your Mac. Nothing is served until you turn remote access on in Settings, at the Mac.

**This is a preview.** Settings says *Preview* next to it. It does part of the job, it has been tested with a stand-in for the relay and with a test client on the same computer, and the parts a person has to try are still open. Read [what it does now](#what-it-does-now) and [what is not verified](#what-is-not-verified-yet) before you rely on it.

It is separate from [phone access](phone-access.md), which uses your assistant provider's own remote features and gives the phone the same reach as the desktop session. Remote access is Garrick's own service, with its own sign-in and its own limits on what a phone may see.

## What it does now

A connected assistant gets five read tools: `places`, `thread_state`, `search`, `read` and `owed`. For changes it gets three tools that work together: `prepare`, `execute` and `status`. They serve ten actions: a note, the six Todo actions, park, wake and checkpoint. Everything else is listed below with the release that plans it, so a partial service is never mistaken for a complete one. Of the verbs, 10 work now, 17 wait for your approval (which does not exist yet, so they are refused), 7 are internal and 33 are planned for a later release.

<!-- manifest -->
| What | Kind | Disposition | Planned | Why |
|---|---|---|---|---|
| `checkpoint` | verb | Served | now |  |
| `note-add` | verb | Served | now |  |
| `park` | verb | Served | now |  |
| `todo-add` | verb | Served | now |  |
| `todo-date` | verb | Served | now |  |
| `todo-done` | verb | Served | now |  |
| `todo-edit` | verb | Served | now |  |
| `todo-retire` | verb | Served | now |  |
| `todo-undo` | verb | Served | now |  |
| `wake` | verb | Served | now |  |
| `recall` | skill | Served | now | Answered by the five read tools. |
| `owed` | read tool | Served | now |  |
| `places` | read tool | Served | now |  |
| `read` | read tool | Served | now |  |
| `search` | read tool | Served | now |  |
| `thread_state` | read tool | Served | now |  |
| `channel-answers` | verb | Owner approval | in a later release | Changes how a channel answers. |
| `chase` | verb | Owner approval | in a later release | Drafts a message to a person who owes an answer. |
| `commit-files` | verb | Owner approval | in a later release | Commits files that the owner has not reviewed. |
| `connected-service` | verb | Owner approval | in a later release | Turns a connected service on or off. |
| `delete` | verb | Owner approval | in the next release | Deletes a project or a thread for good. |
| `inbox-run` | verb | Owner approval | in a later release | Files the contents of an inbox. |
| `intake-answer` | verb | Owner approval | in a later release | Answers a question about where a filed item belongs. |
| `layout` | verb | Owner approval | in a later release | Changes how a project is laid out. |
| `machine-role` | verb | Owner approval | in a later release | Sets the role of this computer. |
| `new-project-party` | verb | Owner approval | in a later release | Adds a party, which decides which side of a wall a project is on. |
| `outbox-drop` | verb | Owner approval | in a later release | Drops a queued action for good. |
| `read-guard` | verb | Owner approval | in a later release | Changes what an assistant may read. |
| `release-update` | verb | Owner approval | in a later release | Replaces the software that serves the request. |
| `run` | verb | Owner approval | in a later release | Starts a scheduled job on this computer. |
| `settings` | verb | Owner approval | in a later release | Changes the workspace settings, such as Ask's own level. |
| `walls-allow` | verb | Owner approval | in a later release | Changes what a wall lets through, and only the owner may decide that. |
| `walls-look` | verb | Owner approval | in a later release | Shows the words a wall holds back, and only the owner may see them. |
| `answer` | verb | Not yet | in a later release |  |
| `ask-desktop` | verb | Not yet | in a later release |  |
| `bring-back` | verb | Not yet | in a later release |  |
| `check-name` | verb | Not yet | in the next release |  |
| `close` | verb | Not yet | in a later release |  |
| `continue` | verb | Not yet | in a later release |  |
| `example` | verb | Not yet | in a later release |  |
| `files` | verb | Not yet | in a later release |  |
| `finding` | verb | Not yet | in a later release |  |
| `fix` | verb | Not yet | in the next release |  |
| `later` | verb | Not yet | in a later release |  |
| `memory-preview` | verb | Not yet | in a later release |  |
| `move` | verb | Not yet | in the next release |  |
| `new-project` | verb | Not yet | in the next release |  |
| `new-thread` | verb | Not yet | in the next release |  |
| `note-open` | verb | Not yet | in a later release |  |
| `open` | verb | Not yet | in a later release |  |
| `question-answer` | verb | Not yet | in a later release |  |
| `question-close` | verb | Not yet | in a later release |  |
| `question-decide` | verb | Not yet | in a later release |  |
| `question-done` | verb | Not yet | in a later release |  |
| `question-later` | verb | Not yet | in a later release |  |
| `question-open-sections` | verb | Not yet | in a later release |  |
| `question-work` | verb | Not yet | in a later release |  |
| `release-check` | verb | Not yet | in a later release |  |
| `rename` | verb | Not yet | in the next release |  |
| `start` | verb | Not yet | in a later release |  |
| `stop-using` | verb | Not yet | in a later release |  |
| `suggestion` | verb | Not yet | in a later release |  |
| `undo` | verb | Not yet | in the next release |  |
| `walls-unallow` | verb | Not yet | in a later release |  |
| `work-file` | verb | Not yet | in a later release |  |
| `wrap` | verb | Not yet | in the next release |  |
| `intake` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `interview` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `knowledge` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `meetings` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `nurture` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `setup` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `threads` | skill | Not yet | in the next release | Park, wake and checkpoint are served. Wrap and the lifecycle verbs come next. |
| `todo` | skill | Not yet | in a later release | The Todo verbs are served. The sweep needs the job worker. |
| `update` | skill | Not yet | in a later release | Needs the job worker, which comes in a later release. |
| `count-card` | verb | Internal |  | Counts a card the status page showed. It has no meaning for a remote assistant. |
| `files-progress` | verb | Internal |  | The service reports the progress of long work itself, in a later release. |
| `files-stop` | verb | Internal |  | The service cancels long work itself, in a later release. |
| `note-read` | verb | Internal |  | It reads a path without asking which zone the path is in. The read tools replace it. |
| `operations` | verb | Internal |  | The service reads the record of operations itself, to answer a status call. |
| `remote` | verb | Internal |  | changes only at the Mac |
| `session-url` | verb | Internal |  | Opens a session in an app on this computer. It has no meaning for a remote assistant. |
<!-- /manifest -->

Reads go through the same readers the Ask window uses, with the same limits: 6,000 characters of a record in one call, a 300-character snippet for each search hit, 1,500 characters of a thread's *Resume here* block, and 40 Todo lines. Each result names its source and its date. The single-note reader is not offered, because it asks no zone question.

A change takes three calls. `prepare` says what would change and gives an operation id. `execute` runs it once, as a click on the page runs it: the same checks, the same commit, the same wall check. It returns at once, because a commit can take longer than an assistant waits for one answer. `status` gives the receipt. A note lands as a dated note in the thread's notes, with its actions in the zone's `Todo.md`, in one commit. A Todo change names its line in words and touches only that zone's `Todo.md`. A checkpoint is written into the thread note, and the next wrap at the desk folds it into the *Resume here* block.

Asking again with the same operation id gives the first result, so asking twice saves once. A changed request under the same id is refused. A change is refused when the file has edits that are not saved to history yet, or a wrap is running on the thread. Prepared changes wait an hour, and receipts are kept for seven days. A token whose scope was narrowed to read cannot write. A repeat that was already done gets the receipt "This was already done a few minutes ago. Nothing was saved again." If a change takes longer than seven minutes, the receipt says it may or may not have been saved, and asks you to check at the Mac. A note may hold up to 4,000 characters, and a Todo line up to 1,000. A note, a new action, park and wake leave a record in the zone's own history folder, written before the commit and closed after it, with the caller named as remote. If the service or its worker stops in the middle of one of these, the next status call reads the zone's history and says once whether the change was saved, was not saved, or cannot be told, and names the commit when it cannot. It never commits a second time. A change that has no such record, such as one begun before an update, says the save did not finish and asks you to check at the Mac. The five Todo line changes (tick, untick, new date, reword, retire) leave the same record, so a stop in the middle of one is settled the same way. A checkpoint makes no commit and has no record: a stop in the middle of one says the save did not finish.

An assistant cannot change what it may see, cannot change a grant and cannot change a setting. Those change only in Settings, at the Mac.

## Reach

Each connected assistant has a grant, and each grant has a reach: the zones it may read and the zones it may write, set at the Mac. By default the reach is the zones that are not walled, Knowledge and Garrick's own docs. A walled zone joins a grant only when you turn it on by name, in Settings, after the notice below. Reading and writing are separate choices, and Garrick records the date. A write can be on without a read.

One connection reaches one walled zone. Turning on a second one is refused with "One connection reaches one walled zone. Use another connection for the second zone." If a connection somehow holds two, it reaches none of the walled zones, and Settings says so. Turn all but one off.

Zone names are not secret. A request that names a walled zone outside the reach gets one answer, "new context required", spoken as "outside what this connection may reach", and nothing is released. A name that is no zone at all gets "No such zone." A project, a thread or a record in a walled zone outside the reach is answered as a place that is not there. No count, title or path changes.

Each answer carries a handle. Handles last twelve hours. When you change a grant's reach at the Mac, its old handles stop working and the assistant is told to start a new chat.

## What leaves the Mac

On a read, the text of each result leaves: up to a few thousand characters of a record for each read, a short snippet for each search hit, the first part of a thread's resume block, titles, dates, and the paths that carry zone, project and thread names, and up to forty Todo lines. On a write, the words you dictate leave in the other direction.

It goes to the relay, which carries it and, with the method this release uses, cannot read it. It then goes to the assistant provider. There it becomes part of the chat: kept in the chat history under that account's settings, shown on every device signed in to the account, and spoken aloud in voice mode. If you point the address at a server of your own, that server can read it.

Revoking access stops new calls. It removes nothing already returned.

## What Garrick cannot enforce

- Another connector in the same chat, such as mail or a drive, can carry a record further. Garrick's rule that anything leaving the machine is confirmed first has no place to act in a chat. A sentence planted in a record could ask the assistant to mail the record, and only the assistant's own approval prompt stands in the way.
- The commit check does not see a chat.
- The service makes sure that no call crosses a grant's reach and that only you change it. It does not prove that a chat is fresh. If you change a reach and keep talking in the old chat, with an assistant that asks for a new handle, two zones can still end up in one chat.

## The notice before a walled zone

Settings shows this before it turns a walled zone on, once for each zone:

<!-- notice -->
> Turning on {zone} lets a connected assistant see what this zone holds. What it reads leaves this Mac. It goes through your address: the relay carries it but cannot read it, and a server of your own that forwards it can. Then it goes to the assistant's provider, where it becomes part of the chat. It stays in the chat history after you revoke access. Another connector in the same chat, such as mail, can carry it further. The commit check does not see a chat.
<!-- /notice -->

## Set it up

You do this at the Mac, in Garrick.app. A browser shows the state and says "Remote access is changed in Garrick.app."

1. Open Settings and find *Remote access*, marked *Preview*. It sits between *Walls* and *Look*.
2. If it says *Not installed*, the row has a button, *Ask my assistant to add it*. There is no one-click install: the button hands the request to your assistant. You can also do it yourself: copy the folder `extras/remote` of your Garrick download to `System/remote` in the workspace, delete `System/remote/tests`, then reopen Settings. Updating Garrick then keeps it current. Installing only copies files. It turns nothing on and fetches nothing.
3. It works on a computer that is *one computer* or the *home server*. On a *laptop copy* Settings says *Cannot be turned on*, and says to turn it on at the Mac that holds your workspace. Nothing listens there.
4. Choose how your assistant will reach this Mac: *Through a relay*, or *Through an address I already have*.
   - With a relay, Garrick uses the relay's app on this Mac to publish the service and reads the address back. Each missing step is one sentence and one next step. The relay's app is not installed, it is not signed in, publishing is not switched on in your relay account, or the relay has not given an address yet. A relay that cannot publish changes nothing: remote access is not left on, and Settings gives the one missing-step sentence. Fix the one named and choose *Turn on* again; once it is on, *Check the address again* does the same check. The relay's name is given to you, not chosen by you. It appears in public certificate logs, and a change of name means adding the connector again.
   - With your own address, type a secure web address: the name of your server with `https` in front of it, and no page after the name. A bare number, a password in it or a local name is refused. The server must forward to this Mac's port, which Details shows.
5. Choose *Turn on*. Turning on, and *Resume*, check the service software first. If it is missing, or older than this release's lock, Garrick says so and sets it up in the background. That takes a few minutes and needs the internet, and the service starts by itself when it is done. After a Garrick update that changes the lock, *Pause* and then *Resume* installs the new software. Settings lists each step: *Remote access is turned on*, *The service software is installed*, *Your address is set*, *The service starts when you log in* and *An assistant is connected*.
6. In your assistant, add a connector with your address followed by `/mcp`, and sign in. Back in Settings, the sign-ins that wait are listed, each with the name the assistant gave and when it started. Each has a sign-in number, and the sign-in page shows the same number. Pick the sign-in you started, and check that its number matches the number on your sign-in page, then choose *Show a code*. Two sign-ins can have the same name and start time, so the name is not enough. The number shows which row in Settings belongs to which sign-in page. It does not show who opened that page: a link a stranger sent you opens a page with a number too, and a code made for that row works there. Go on only if you started the sign-in yourself. With one waiting, it is picked for you; with none, there is no code to show. A code is refused while no address is set. Type the six-digit code on that sign-in's page within five minutes. It works once, and only for the sign-in you picked. If the sign-in you picked has run out or been pushed out in the moment before the code is made, you get no code and Settings says that sign-in is not waiting any more. Typed on another sign-in, it is refused, it counts as a wrong code on that sign-in, and it stays good for the one it was made for.
7. On the sign-in page, *Read* is ticked and is always granted. Tick *Save notes and actions in them* only if this assistant may write.

The sign-in page is open to the internet, so anyone with a sign-in link can type a code on it. Each sign-in request has its own five tries. The fifth wrong code closes that request, and the code made for it, and you start it again in your assistant. Other sign-ins stay open, so a stranger's wrong codes on a sign-in of their own never use up your tries. A flood across many sign-ins reaches a shared ceiling: 30 wrong codes in 15 minutes on sign-ins that no code was made for. After that, a sign-in with no code made for it takes no code for 15 minutes. A sign-in that you made a code for is outside the ceiling, and *Show a code* still works under it, so a flood cannot lock you out of the sign-in you started. What a flood can still do: close sign-ins that it can reach, fill the 50 places for waiting sign-ins, and fill the sign-in page's limit of calls (30 in 10 minutes from one caller, 120 from all callers), which refuses the page for the rest of that window. Behind a relay all callers count as one, so a flood of 30 calls to the sign-in page in 10 minutes closes it for everyone, you included, for up to ten minutes. Nothing connects. If it happens, wait ten minutes and start again. A flood on the sign-in routes slows calls, by about a second and a half each, while it lasts, and can fill the registration and consent limits. A token refresh is refused only above 5,000 calls a minute from one caller, and behind a relay all callers count as one; above 20,000 a minute in all, it is refused for everyone. A sign-in request may be at most 64 KB. At most 50 sign-ins can wait at once, and each waits 10 minutes. When 50 wait, the oldest is dropped and the new one is kept, so a flood never shuts a new sign-in out. A flood can still push out a sign-in that is waiting and has no code yet. If yours is gone, start the sign-in again in your assistant. A sign-in that a code is waiting for is never the one dropped. Grants that exist keep working. A client that sends a `state` longer than 300 characters gets `invalid_request`. Access tokens last 10 minutes. Refresh tokens last 30 days and rotate, and a refresh token used twice closes the grant. The sign-in page says when the sign-in was started, and asks you to go on only if you started it yourself a moment ago. A wrong code counts only while a code is waiting, and a new code does not give a sign-in more tries. A code made for one sign-in and typed on another is refused, and it counts as a wrong code on the sign-in it was typed on. The sign-in sends you back only to the assistant's published callback, or to this computer for a command-line client.

Garrick keeps the service's software, its list of grants and its log in a folder for Garrick under your Library, never in the workspace and never in git. The service has its own Python 3.12 and its own packages, installed from a lock file whose hashes must all match. A hash that does not match stops the install. The log holds the time, the tool, the grant, the outcome and how long it took, and nothing else: no token, no code, no search words and no record's text. The service listens on this computer only, on port 8781 unless you change it.

When you turn a walled zone on, Garrick keeps a marker of that zone's folder with the grant, and every call compares it. If you remove the zone and make a new one under the same name, the marker no longer fits, so the new zone starts with nothing, and you turn it on again in Settings. A chat or a prepared write from before the zone was made again stays refused after you turn the new zone on, and the refusal says it was prepared before you changed what the connection may reach. Ask for the same change again in a new chat: it is prepared as a new operation and runs. Editing files inside the zone does not change the marker. A zone turned on with Garrick 0.82.0 or earlier has no marker, so it stays out of reach until you turn it on again in Settings. If the marker cannot be read, the zone is out of reach. That includes a disk that keeps no creation time for folders, where a zone cannot be turned on: Settings says so, and the next step is to keep the zone on a disk that records it, such as the Mac's own disk. The marker also holds the disk's device number, so a zone on an external or network volume whose device number changes goes off until you turn it on again in Settings.

## Pause, revoke and turn off

In Settings:

- *Pause* closes access at once, with no restart. Nothing is uninstalled and every grant stays. *Resume* opens it again.
- *Revoke*, on a connected assistant, removes that grant. Its next call is refused.
- *Turn off* removes the start-up agent and clears a code that is waiting. Your connected assistants stay listed, and none of them can get in.

Each of them blocks the very next call. They do not take back what an assistant already read. Under *What it may reach*, each walled zone has *Read* and *Write* boxes. Ticking one shows the notice above, and the zone is turned on only when you choose *Turn on*.

## When the Mac cannot answer

If the Mac is off or asleep, you see the assistant's own error, not a sentence from Garrick. Nothing in Garrick can answer for an absent host. A laptop sleeps when its lid is shut. After a power cut, a Mac with FileVault serves nothing until someone logs in at it. The service starts at login and keeps running while remote access is on.

## What is not verified yet

- The relay adapter is not yet verified on a real Mac. It drives the Tailscale command line, the one inside its app or else `tailscale` on the path, and it has been tested against a stand-in only. Whether the address survives a restart and sleep through the real relay is open (A2). Whether the relay passes on the caller's address is treated as not known, so the sign-in limits cannot rely on it.
- The "I already have an address" adapter is the tested path. Passing on the caller's address is off for it by default.
- Using it by voice from a phone, with the approval taps counted, is open (A13). Both need a person.
- There is no list of tested assistants yet. That comes with a later release.

## What is not in this release

Approvals from the phone, switching a reach from the phone, wrap, the lifecycle verbs, owner-only operations and long jobs. Sign-in with a passkey comes in a later release.

## What you lose without it

Only the service. Everything else in Garrick works without it, and nothing here changes when it is off.
