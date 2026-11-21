# One workspace on more than one machine

Garrick assumes one machine. This page is for one other setup: an always-on machine at home that holds the workspace and runs the sessions and the nightly jobs, and a laptop that keeps a copy to read with no network. If you work on one machine, skip it. Nothing here changes how Garrick works for you.

## The three roles

Each machine has a role. The role belongs to the machine, not to the workspace, so it is not in `System/garrick-settings.json`: a sync would copy that file to the other machine.

| Role | What it is |
|---|---|
| `solo` | One machine does everything. This is how Garrick works, and the default. |
| `server` | Holds the workspace that counts. Runs the sessions and the jobs. The only machine that commits. |
| `roaming` | Holds a copy that only receives. A session here reads. It writes only in a drop folder. |

The role is in one small file outside the workspace, `~/.config/garrick/machine.json`:

```json
{ "role": "roaming", "name": "laptop", "server": "mini", "workspace": "/Users/jo/Garrick" }
```

`name` is this machine's name, and `server` is the server's. `workspace` is where the workspace sits on this machine. `peers` may list the names of other machines that sync with this one. With no file, or a file Garrick cannot read, or a role it does not know, the role is `solo`.

Write the file with the command below. Run it yourself, in a terminal. The zone guard refuses a file-editing tool's write to that one file, and to the temporary file beside it, on every role. The rest of `~/.config/garrick/` (the mail, bridge certificate and Telegram files) is as before. The guard covers the file-editing tools only: a shell command can still change the role file. It stops a mistaken edit. It is not a lock.

```sh
python3 System/tools/machine.py set --role roaming --name laptop --server mini --workspace ~/Garrick
python3 System/tools/machine.py
```

The second command says the role. The `setup` skill asks for a role only when you tell it the workspace is on more than one machine, and then shows you this command.

## What each role changes

On `server`:

- The jobs run as they do on `solo`.
- `drift.py` skips a share link that does not lead anywhere here, and says once that the link is not reachable here. It does not fail every row under it.
- `check.py` warns about sync conflict copies anywhere in the workspace: Syncthing's `*.sync-conflict-*`, Dropbox's `* (conflicted copy)*`, and OneDrive's `<name>-<machine>.<ext>` for a machine name `machine.json` knows. Each zone reports its own copies.

On `roaming`:

- A job does not run. `job.py` says so and stops, and `check.py` reports an error for a Garrick launchd agent that is loaded. Unload it with `launchctl bootout`.
- The zone guard refuses a write anywhere in the workspace outside the drop folders: each zone's `Inbox/` and the workspace's own `Inbox/`. The refusal says why and names the drop folder to use.
- Every zone's pre-commit check refuses a commit. The server commits.
- A Todo action made on the status page waits in an outbox. See below.

## Sync stays your tool

Garrick ships no sync tool. It needs two rules from the one you pick.

1. **The main folder syncs one way, from server to roaming.** With Syncthing, make the folder Send Only on the server and Receive Only on the laptop. Do not use iCloud Drive or Dropbox for the workspace: they remove local copies and write conflict copies inside `.git`.
2. **The drop folders sync in both directions.** They are the only way back from the laptop: notes to yourself and mail saved offline, results of `drift.py`, and the outbox. Intake on the server files them on its next run. It leaves the hidden folders `.outbox/` and `.machines/` alone.

Both machines must hold the workspace at the same absolute path, because hooks, memory folders and links keep absolute paths. On the server, `check.py` records its path in `System/generated/server-path.json`, which the sync carries, and on the roaming machine it warns when the local path differs.

## A share on one machine only

A share link under a zone's `.shared/` may resolve on one machine only, for example because of an organisation's sign-in. Nothing on the server reads through a link that does not resolve.

- The `threads` skill's Wrap records the `published.md` row, as it does everywhere, and adds a line to the zone's `Todo.md` to copy the file from the machine that reaches the share. A copy to a share is a send, so it asks first when it is made.
- On the machine that reaches the share, run `python3 System/tools/drift.py --save`. On a roaming machine this does not write `System/generated/drift.json`. It writes what it found, one zone at a time, to `Zones/<Zone>/Inbox/.machines/drift-<name>.json`. On the server, `drift.py --save` reads those files, if they are less than two weeks old, and the status page shows the rows. A link they cover is no longer reported as not reachable.

## Todo actions from a roaming machine

A roaming machine never edits `Todo.md`. On its status page, the four Todo actions (tick, untick, reword, add) are written as requests in `Zones/<Zone>/Inbox/.outbox/` instead. The row shows "ticked, waits for the server".

A tick made by hand in Obsidian counts too. When the page refreshes, the status app compares the `Todo.md` the sync last delivered, which it keeps in the jobs folder outside the workspace, with the file, and turns each new `[x]` into a request. No launchd agent does this.

On the server, a page build applies each request through `page_action.py`, with the same lock, commit and wall check as a tick made there, and takes the file out. Requests are applied in the order they were made, not the order of their file names. An id is applied once. You can also run `python3 System/status/outbox.py replay`.

If the line changed on the server in the meantime, its key no longer matches. The server holds the request and the Todo tab asks: *Show me the line*, or *Drop it*. The held file comes back to the laptop with the next sync, so the laptop's Todo tab asks too. Nothing is applied until you decide, and *Drop it* applies nothing: it removes the held file from the drop folder, on the server or on the laptop, which is a place the laptop may write. Only a refusal that is about the line holds a request: a changed line, a refusal by the wall check, a duplicate add, a request that does not pass its checks. A busy lock, a timeout or a git that did not run says nothing about the line, so the request stays in the outbox and the next run tries it again. Later requests of that zone wait behind it, so that a tick and a later untick never swap.

If you tick a line by hand and then reopen it by hand before the server applies the tick, the roaming machine writes an untick request after the tick. The tick stays: the server applies both, in order, and the line ends open. Park, wake, rename and delete change folders, so they wait until the roaming machine can reach the server.

## What this does not cover

- Two machines that both write. That needs a merge rule for every shared file, and git does that better than a sync tool.
- Running the model on the server. That is a question about assistants, not machines.
