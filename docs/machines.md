# One workspace on more than one machine

## Do you need this?

If you work on one computer, you do not. Skip this page: nothing here changes how Garrick works for you, and the default role, **One computer**, is what you have now.

This page is for one other setup: a computer at home that stays on and holds the workspace, and a laptop that keeps a copy to read, even with no network.

## The three roles

Each computer has a role. You set it in Settings, under *This machine*. The role belongs to the computer, not to the workspace, so a sync never copies it to the other computer. A role's name in the file that holds it is in brackets.

| Role | What it is |
|---|---|
| **One computer** (`solo`) | Everything happens here: your sessions, the nightly jobs and your Todo lists. This is how Garrick works, and the default. |
| **Home server** (`server`) | This computer is always on and holds the real workspace. The nightly jobs run here, and it applies the ticks your laptop sends. It is the only computer that commits. |
| **Laptop copy** (`roaming`) | This computer keeps a copy that only receives. You can read everything, even with no network. A tick on a Todo list waits until the home server applies it. Nightly jobs do not run here. |

With no role set, or a file Garrick cannot read, the role is One computer.

## Two computers and one workspace

![Two computers and one workspace. On the left, the home server, which is always on: the sessions and the nightly jobs write to the workspace, the copy that counts, and commit there. On the right, the laptop copy: a read-only copy of the workspace, the status page, and the drop folders. A sync tool joins them. The workspace goes one way, from the server to the laptop: send only on the server, receive only on the laptop. Back from the laptop come only the drop folders, which sync in both directions and hold the inbox files and the Todo requests, and the results of the shared-library check. The shared library is reached from the laptop only, and its result goes to the server through the drop folders.](assets/two-computers-one-workspace.png)

The home server holds the workspace, runs your sessions and the nightly jobs, and makes the commits. The main folder syncs one way, from the server to the laptop. Back from the laptop come only the drop folders (each zone's `Inbox/`, and the workspace's own), the Todo outbox and the result of the shared-library check.

Both computers must hold the workspace at the same absolute path, because hooks, memory folders and links keep absolute paths. On the server, `check.py` records its path in `System/generated/server-path.json`, which the sync carries, and on the laptop it warns when the local path differs.

### The shared library

A shared library under a zone's `.shared/` may be reachable from one computer only, for example because of an organisation's sign-in. Nothing on the server reads through a link that does not resolve: `drift.py` skips it, says once that the link is not reachable here, and does not fail every row under it.

- The `threads` skill's Wrap records the `published.md` row, as it does everywhere, and adds a line to the zone's `Todo.md` to copy the file from the computer that reaches the share. A copy to a share is a send, so it asks first when it is made.
- On the computer that reaches the share, run `python3 System/tools/drift.py --save`. On a laptop copy this does not write `System/generated/drift.json`. It writes what it found, one zone at a time, to `Zones/<Zone>/Inbox/.machines/drift-<name>.json`, a drop folder. On the home server, `drift.py --save` reads those files, if they are less than two weeks old, and the status page shows the rows. A link they cover is no longer reported as not reachable.

## A tick on the laptop

![A tick on the laptop. You tick a line on the laptop's status page. The page writes a request in the Todo outbox, a drop folder, and the row says it waits for the server. The sync tool carries the request home. The home server's next page build applies it: it ticks the line in Todo.md and commits. The sync tool carries the new Todo.md back to the laptop, the laptop copy refreshes, and the row shows ticked. If the line changed on the server in between, the request is held, nothing is applied, and the Todo tab asks: Show me the line, or Drop it.](assets/a-tick-on-the-laptop.png)

A laptop copy never edits `Todo.md`. On its status page, the four Todo actions (tick, untick, reword, add) are written as requests in `Zones/<Zone>/Inbox/.outbox/`, and the row shows "waits for the server".

A tick made by hand in Obsidian counts too. When the page refreshes, it compares the `Todo.md` the sync last delivered, which it keeps in the jobs folder outside the workspace, with the file, and turns each new `[x]` into a request. No launchd agent does this.

On the server, a page build applies each request through `page_action.py`, with the same lock, commit and wall check as a tick made there, and takes the file out. Requests are applied in the order they were made, and each id once. You can also run `python3 System/status/outbox.py replay`.

If the line changed on the server in the meantime, its key no longer matches. The server holds the request, and the Todo tab asks: *Show me the line*, or *Drop it*. The held file comes back to the laptop with the next sync, so the laptop's Todo tab asks too. Nothing is applied until you decide, and *Drop it* applies nothing: it removes the held file from the drop folder, on the server or on the laptop. Only a refusal that is about the line holds a request: a changed line, a refusal by the wall check, a duplicate add, a request that does not pass its checks. A busy lock, a timeout or a git that did not run says nothing about the line, so the request stays in the outbox and the next run tries it again. Later requests of that zone wait behind it, so that a tick and a later untick never swap.

If you tick a line by hand and then reopen it by hand before the server applies the tick, the laptop copy writes an untick request after the tick. The tick stays: the server applies both, in order, and the line ends open.

## Set it up

1. On the home server, open Garrick.app, then Settings, then *This machine*, and choose *Change…*. Choose **Home server**, give the computer a name if you like, and say yes.
2. On the laptop, do the same and choose **Laptop copy**. It asks for the home server's name.
3. Set up the sync, which Garrick does not ship. It needs two rules from the tool you pick.
   - **The main folder syncs one way, from the home server to the laptop.** With Syncthing, make the folder Send Only on the server and Receive Only on the laptop. Do not use iCloud Drive or Dropbox for the workspace: they remove local copies and write conflict copies inside `.git`.
   - **The drop folders sync in both directions.** They are the only way back from the laptop: notes to yourself and mail saved offline, results of `drift.py`, and the outbox. Intake on the server files them on its next run. It leaves the hidden folders `.outbox/` and `.machines/` alone.
4. Keep the workspace at the same absolute path on both computers.

The role is kept in one small file outside the workspace, `~/.config/garrick/machine.json`, which Settings writes for you. In a browser, *This machine* shows the role and says it is changed in Garrick.app.

The `setup` skill asks for a role only when you tell it the workspace is on more than one computer, and then points you here.

**If you cannot use the app.** The same change, in a terminal:

```sh
python3 System/tools/machine.py set --role roaming --name laptop --server mini --workspace ~/Garrick
python3 System/tools/machine.py
```

`--role` takes the names in brackets in the table above. The second command says the role. `name` is this computer's name, `server` is the server's, and `workspace` is where the workspace sits on this computer. `peers` may list the names of other computers that sync with this one, and a change in Settings keeps what a file already names that the change does not set: its peers, its workspace path, and its name when you leave the name empty. The zone guard refuses a file-editing tool's write to that one file, and to the temporary file beside it, on every role. The rest of `~/.config/garrick/` (the mail, bridge certificate and Telegram files) is as before. The guard covers the file-editing tools only: a shell command can still change the role file. It stops a mistaken edit. It is not a lock.

## What you cannot do on the laptop

On a laptop copy, each of these is refused, and the refusal says why:

- **Park, wake, rename, move and delete.** They change folders in the workspace, and this computer only receives it. Do them on the home server.
- **Anything that writes in the workspace outside a drop folder.** The zone guard refuses a file-editing tool's write anywhere but each zone's `Inbox/` and the workspace's own `Inbox/`, and the refusal names the drop folder to use.
- **Commits.** Every zone's pre-commit check refuses one. The home server commits.
- **The nightly jobs.** A job does not run: `job.py` says so and stops, and `check.py` reports an error for a Garrick launchd agent that is loaded. Unload it with `launchctl bootout`.
- **The read guard's settings.** They live in the workspace, so Settings leaves them to the home server: on a laptop copy the *Read guard* block shows one line, “The read guard is set on the home server.”, in place of its controls. A laptop copy can still change its own role.

On the home server, the jobs run as they do on one computer, and `check.py` warns about sync conflict copies anywhere in the workspace.

## When something goes wrong

- **A conflict copy.** A sync leaves one when both computers changed a file. `check.py` names them: Syncthing's `*.sync-conflict-*`, Dropbox's `* (conflicted copy)*`, and OneDrive's `<name>-<machine>.<ext>` for a computer name the role file knows. Each zone reports its own copies. Keep the file you want and remove the copy.
- **A laptop off the network for weeks.** It keeps working from its last copy, and every Todo action waits in the outbox. When the sync reaches the server again, the server applies the requests in order. A line that changed meanwhile is held, and the Todo tab asks.
- **Changing a role later.** Use *Change…* again, on that computer only. The other computer keeps its own role. Changing a laptop copy to one computer lets its jobs run again as soon as their launchd agent is loaded. Garrick does not load one for you.

## What this does not cover

- Two computers that both write. That needs a merge rule for every shared file, and git does that better than a sync tool.
- Running the model on the server. That is a question about assistants, not computers.
