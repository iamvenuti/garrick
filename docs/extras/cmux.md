# Extra: cmux, one terminal tab per thread

This is an optional extension of the [terminal route](../terminal-setup.md). Run Claude Code or Codex CLI inside it; no provider desktop app is required for local work. [Phone access](phone-access.md) is a separate matter, and what it needs differs by provider.

cmux is a Mac terminal built for running several assistant sessions side by side, one per tab. That maps onto Garrick's model: a tab for each thread you are working on, started in the thread's folder, with the thread's conversation in it. The cmux extra, `extras/cmux/`, adds a skill and a command, both called `desk`, that keep it that way for you: by voice, typed, or from the [status page](status-page.md).

## What it adds

- **"Open Pricing"** opens a tab in the Pricing thread's folder, in a cmux workspace named after its zone, with a session named "Acme Review, Pricing" that starts on "open Pricing" and answers in two sentences. If the tab is already open, desk brings it forward instead, and sends the phrase only when the session there is idle.
- **"Close Pricing"** has the session in that tab wrap the thread, then closes the tab. "Close the Pricing tab" closes it without a wrap.
- **"Close for the day"** wraps each tab used today, one at a time, each in its own session, then runs any commands you set to run before quitting, such as a backup, then quits cmux. A wrap that does not finish stops it with cmux still running, and a notification says which tab.
- **"Shut everything down"** quits cmux without wrapping. Every tab comes back when cmux starts again.
- **"Start the day"** or **"restore my tabs"** starts cmux, or restores its last tabs, then puts the right session back into any tab that came back at a bare prompt.
- **"What tabs are open"** lists them: workspace, tab, assistant, idle or working, folder.

desk works with Claude Code and Codex sessions alike. It tells idle from working by reading each session's own transcript, never the tab's title, and it refuses to close, wrap or quit under a session that is mid-turn or waiting on a question, or one whose transcript it cannot read. A wrap can take minutes, so each tab is checked again the moment its wrap is sent, and one that has started a turn since, or stopped on a question, gets nothing typed into it. Before it does anything that closes or quits, it says what it would do and waits for you to say yes.

These phrases are in `System/rules.md`, under Voice. Without the extra, "close X" and "close for the day" are wraps done from the session you are in, and "open X" opens the thread there.

## Set it up

You need cmux and `python3`. desk runs from the Garrick download you keep, like the other extras, so when you update Garrick, desk updates with it.

1. Copy the skill into your workspace, so your assistants find it:

   ```sh
   cp -R /path/to/garrick/extras/cmux/desk ~/Garrick/System/skills/
   ```

2. Put the command on your PATH, so the skill can run it by name:

   ```sh
   ln -s /path/to/garrick/extras/cmux/desk.py ~/.local/bin/desk
   ```

3. Optionally, copy `extras/cmux/desk.example.json` to `System/desk.json` in your workspace and change what you need. Every setting is optional:

   | Setting | What it does | Default |
   |---|---|---|
   | `workspaces` | The cmux workspace each zone's tabs go to; `neutral` is for System and the wikis | each zone's own name, and *System* |
   | `skip` | Folder names desk passes over | `archive`, `Archive`, `Inbox` |
   | `aliases` | Heard names, on top of the Aliases table in `System/context.md` | none |
   | `agent` | The assistant a new tab starts: `claude` or `codex` | `claude` |
   | `before_quit` | Commands "close for the day" runs, in order, from the workspace root, after the wraps and before cmux quits | none |
   | `socket_password_file` | Where the cmux socket password is kept (below) | `cmux-socket.password` in the jobs folder |

desk finds the workspace the way the other tools do: `--workspace`, or `GARRICK_WORKSPACE`, or the folder you are in, or `~/Garrick`. It keeps its record of which session sat in which tab, `desk-snapshot.json`, and its shutdown log, `desk-shutdown.log`, in the jobs folder: `~/Library/Logs/garrick-jobs/`, or `GARRICK_JOBS_DIR`.

Run `desk status` to check it can see cmux.

## From the status page

With the extra beside `extras/status` in the download, the [status page](status-page.md)'s buttons can open and close a thread's tab, and start up or shut down cmux, through `extras/status/page_action.py`. Those buttons run desk from outside cmux, which cmux turns away until its socket is in password mode.

## The socket password

cmux's control socket accepts only processes cmux itself started. Inside a cmux tab, desk needs nothing more. From the status page's app, or anything else outside cmux, cmux refuses with *Access denied - only processes started inside cmux can connect*.

To let them in, switch cmux to password mode:

1. In cmux, open **Settings › Automation**, set socket access to password, and set a password.
2. Save the same password in a file only you can read. With the password on the clipboard:

   ```sh
   mkdir -p ~/Library/Logs/garrick-jobs
   (umask 077; pbpaste > ~/Library/Logs/garrick-jobs/cmux-socket.password)
   ```

   desk refuses the file if anyone else can read it.
3. Check: `desk status`, from a terminal outside cmux, lists your tabs.

desk passes the password to cmux in its environment, as cmux's own `CMUX_SOCKET_PASSWORD`, never on a command line, where other processes could read it. If `CMUX_SOCKET_PASSWORD` is already set, desk uses that instead of the file; `GARRICK_CMUX_PASSWORD_FILE` or `socket_password_file` names another file.

Keep the password in cmux's Settings, not in `cmux.json`. cmux moves it out of that file into Settings on its own, and a move that goes wrong leaves password mode on with no password, which refuses every client, cmux's own command included.

The trade: any process running as you that can read the file can type into every terminal cmux has open. To undo it, set socket access in **Settings › Automation** back to cmux processes only, and delete the file. The status page's tab buttons are then refused again, and everything inside cmux works as before.

## When cmux brings its tabs back

cmux can restore its tabs after a restart, but the assistant does not always come back inside them: in testing, Claude Code came back in some tabs while others opened at a bare prompt, and Codex did not come back in any. "Start the day" deals with that from desk's record of the last quit. It types the resume command only into a tab that it brought back itself, by starting cmux or restoring its tabs, and only when a shell alone holds that tab: never into an editor or a password prompt. If cmux was already running with sessions open, it resumes nothing. The record is used once, and ignored when cmux has started a session since it was written. Without desk, start the session again with the assistant's own resume command, typed in the tab's folder:

- Claude Code: `claude --resume <id>`, or `claude --continue` for the most recent conversation.
- Codex: `codex resume <id>`, or `codex resume --last`.

Whatever came back, "open [thread]" rebuilds the context from the thread's resume point, so a fresh session loses nothing the work depends on.

## Take it out

Delete `System/skills/desk`, the `desk` link and `System/desk.json`, and switch the socket back as above. Nothing else in the workspace refers to them.

## What you lose without it

Nothing about Garrick itself. One thread at a time, in whatever terminal or terminal tab you already use, works exactly the same: the resume point lives in the thread note, not in cmux's session state, so closing a plain terminal and opening a new one loses you nothing that "open [thread]" doesn't put straight back in front of you. What you lose is a tab per thread kept for you, each wrap done in its thread's own session, and the tabs brought back the next morning.
