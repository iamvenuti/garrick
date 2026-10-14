# Extra: cmux, one terminal tab per thread

This is an optional extension of the [terminal route](../terminal-setup.md). Run Claude Code or Codex CLI inside it; no provider desktop app is required for local work. [Phone access](phone-access.md) is a separate matter, and what it needs differs by provider.

cmux is a Mac terminal built for running several assistant sessions side by side, one per tab. That maps onto Garrick's model: a tab for each thread you are working on, started in the thread's folder, with the thread's conversation in it. The cmux extra, `extras/cmux/`, adds a skill and a command, both called `desk`, that keep it that way for you: by voice, typed, or from the [status page](status-page.md).

## What it adds

- **"Open Pricing"** opens a tab in the Pricing thread's folder, in a cmux workspace named after its zone, with a session named "Acme Review, Pricing" that starts on "open Pricing" and answers in two sentences. If the tab is already open, desk brings it forward instead, and sends the phrase only when the session there is idle.
- **"Close Pricing"** has the session in that tab wrap the thread, then closes the tab. "Close the Pricing tab" closes it without a wrap.
- **"Close for the day"** wraps each tab used today, one at a time, each in its own session, then runs any commands you set to run before quitting, such as a backup, then quits cmux. A wrap that does not finish stops it with cmux still running, and a notification says which tab.
- **"Back"**, **"where was I"** or **"back to Pricing"** takes a thread held by "I'm being interrupted" off the stack and opens its tab, where the session reads back where you were, the next step and what you had in mind. "Close for the day" names the threads still held and leaves them held: their tabs are not wrapped over what you said when you were cut off.
- **"Shut everything down"** quits cmux without wrapping. Every tab comes back when cmux starts again.
- **"Start the day"** or **"restore my tabs"** starts cmux, or restores its last tabs, then puts the right session back into any tab that came back at a bare prompt.
- **"What tabs are open"** lists them: workspace, tab, assistant, idle or working, folder.
- **A zone's colour.** A zone given a colour in the status page's [Settings › Zones](status-page.md#settings), kept in `System/garrick-settings.json` and committed with the workspace, colours its cmux workspace: desk sets it with `cmux workspace-action --action set-color` each time it opens a tab in one of the zone's projects or threads. A tab at the workspace root, in a wiki or in System takes no colour, and neither does a tab sent to another workspace with `--workspace`. Changing a colour in Settings recolours the zone's workspace if it is open, and taking one away clears it. `desk colour` does the same by hand: with zones named, it colours each one's workspace, or clears it when the zone has no colour; with none named, it colours every zone that has one and clears nothing. cmux has no workspace icon, so its own tab bar shows the colour alone.

desk works with Claude Code and Codex sessions alike. It tells idle from working by reading each session's own transcript, never the tab's title, and it refuses to close, wrap or quit under a session that is mid-turn or waiting on a question, or one whose transcript it cannot read. A Claude Code tab with no prompt since it started or was cleared with `/clear` has no transcript yet; desk reads it as `empty`, idle with nothing to wrap, and closes it without one. A wrap can take minutes, so each tab is checked again the moment its wrap is sent, and one that has started a turn since, or stopped on a question, gets nothing typed into it. Before it does anything that closes or quits, it says what it would do and waits for you to say yes.

These phrases are in `System/rules.md`, under Voice. Without the extra, "close X" and "close for the day" are wraps done from the session you are in, and "open X" opens the thread there.

## Set it up

You need cmux and `python3`. desk lives in your workspace, like the status page, so [updating Garrick](../updating.md#extras) updates it with the rest.

1. Copy the command and its library into your workspace as `System/cmux/`, and the skill into `System/skills/`, so your assistants find it. Then commit both in the workspace root's repository:

   ```sh
   mkdir -p ~/Garrick/System/cmux
   cp /path/to/garrick/extras/cmux/*.py /path/to/garrick/extras/cmux/desk.example.json ~/Garrick/System/cmux/
   cp -R /path/to/garrick/extras/cmux/desk ~/Garrick/System/skills/
   ```

2. Put the command on your PATH, so the skill can run it by name:

   ```sh
   ln -s ~/Garrick/System/cmux/desk.py ~/.local/bin/desk
   ```

   A `desk` linked to a Garrick download instead, as these steps once said, still works. The next update points it at the workspace's copy, and says so before it does.

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

When desk is asked to open a folder with a prompt and a tab there is idle, the prompt goes to that tab; if it is mid-turn, nothing is sent; if desk cannot read its state, as with a session cmux remembers whose transcript is gone, a new tab starts on the prompt.

With the extra in `System/cmux/`, beside the status page in `System/status/`, the [status page](status-page.md)'s buttons can open and close a thread's tab, and start up or shut down cmux, through `System/status/page_action.py`. Those buttons run desk from outside cmux, which cmux turns away until its socket is in password mode.

Once the page says the desk is ready (the extra and cmux), everything in Garrick.app that opens cmux goes through desk, so the tab starts the assistant instead of waiting at a prompt with the phrase on the clipboard:

| Where | What the tab starts on |
|---|---|
| *Open in cmux* on a card, in the graph's panel, and a thread's name when cmux is the default | "open Acme Review, Pricing" |
| A cmux icon in the menu bar menu or the panel, and a row's name when cmux is the default | the same |
| *Process the Inbox*, in the menu and the panel, when cmux is the assistant | "process the inbox", in a tab at the workspace root |
| The menu's or the panel's field, with the preview `ask` off and cmux the assistant | the words you typed, at the workspace root |
| Ask, with the preview `ask` on, opening a project or thread in cmux | "open Acme Review, Pricing" |

A tab at the workspace root goes to the *System* workspace (the `neutral` setting), named for what it does: *Inbox* for *Process the Inbox*, and the first few words of the question for *Ask Garrick*, so two of them are told apart and "close the Inbox tab" works. Opened by hand without a name, it is *Workspace*, never the folder's name. desk opens the root only when given its full path, so a heard name never lands there. If a tab is already open in that folder, desk brings it forward, and sends the words only when its session is idle. Without the desk, each of these opens the folder in cmux with the phrase on the clipboard, as before. The [Obsidian plugin](status-page.md#in-obsidian) gets the page's buttons the same way.

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

## A sidebar

cmux's own sidebar describes each workspace by its git branch and each tab by its full path. In a Garrick workspace the branch is almost always `main`, and the paths are long. `extras/cmux/garrick-sidebar.js` replaces it with what you want to see: each cmux workspace by name with its unread count, and under it one line per tab, named by its thread. A tab titled by a path, or by the program in it (Claude Code, Codex, a shell), shows the last part of its folder instead, which is the thread's name for a tab desk opened. Each tab's dot is blue while its agent is working, orange when it has an unread notification, and grey otherwise. A finished turn alone does not colour it. A workspace with a colour in cmux, such as a zone's that desk set, has a bar of it before its name. The zone's icon is not drawn there: the sidebar cannot read the file that names it. Click a workspace to select it, or a tab to focus it. Garrick's mark sits on top, and clicking it opens the status page, if one has been built.

To use it:

```sh
mkdir -p ~/.config/cmux/sidebars
ln -s /path/to/garrick/extras/cmux/garrick-sidebar.js ~/.config/cmux/sidebars/garrick.js
cmux sidebar select garrick
```

`cmux sidebar validate garrick` checks it. Right-click the sidebar button to switch back to cmux's own, which can still drag workspaces into another order; this one cannot yet. The sidebar reads only what cmux tells it about its own workspaces and tabs: it has no access to files, so it does not read thread notes, and the mark opens the status page by its usual path, `System/generated/status.html` in the workspace one of your tabs is in. It is drawn in the mark's dark-ground colours, since cmux does not tell a sidebar whether it is light or dark. The installer does not add it, as with every extra, and an update does not touch it: link it to a Garrick you keep updated, or copy it again after an update.

## Take it out

Delete `System/cmux`, `System/skills/desk`, the `desk` link and `System/desk.json`, and switch the socket back as above. Nothing else in the workspace refers to them. If you use the sidebar, run `cmux sidebar select` for another one, or right-click the sidebar button, and delete `~/.config/cmux/sidebars/garrick.js`.

## What you lose without it

Nothing about Garrick itself. One thread at a time, in whatever terminal or terminal tab you already use, works exactly the same: the resume point lives in the thread note, not in cmux's session state, so closing a plain terminal and opening a new one loses you nothing that "open [thread]" doesn't put straight back in front of you. What you lose is a tab per thread kept for you, each wrap done in its thread's own session, and the tabs brought back the next morning.
