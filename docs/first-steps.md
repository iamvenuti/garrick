# Desktop first steps

Use Garrick in a normal app window. Choose **the Code tab of Claude's desktop app** or **Codex in the ChatGPT desktop app**. After installation, you ask the assistant to manage the files and run Garrick's tools. You do not need Obsidian, cmux or a mail connection.

Allow about 30 minutes to prepare the Mac, longer if downloads or account setup take time. Then follow [Your first useful session](first-session.md) to turn one conversation into a brief and a saved next action. A [guided session](guided-session.md) combines setup and that first piece of work in up to two hours.

Comfortable in Terminal? [Terminal setup](terminal-setup.md) gives you a route without a provider's desktop app.

## 1. Choose one assistant

| Use | What to open |
|---|---|
| Claude | The [Claude desktop app](https://claude.com/download), with access to its Code tab. A plan with Claude Code access is required. |
| Codex | The [ChatGPT desktop app](https://learn.chatgpt.com/docs/app), switched to Codex, with Codex enabled for your account and workspace. |

Install only the one you want to use. For employer material, use an approved account and assistant. The workspace stays on your Mac; material the assistant reads goes to its provider. Check the app's current Mac requirements and account access before proceeding.

## 2. Prepare git and Python

Garrick uses these to save history and run its checks. This is the part done in Terminal, with help if wanted.

Open Terminal: press Command and Space, type `Terminal`, and press Return. Copy this command into it and press Return:

```sh
xcode-select --install
```

A window asks whether to install the command line developer tools, with three buttons: **Get Xcode**, **Not Now** and **Install**. Click **Install**, not Get Xcode, which is a much larger app you don't need, then agree to the licence. The Mac may ask for its password. The download and installation take 5 to 15 minutes. On a Mac managed by your employer, the IT team may need to do this for you.

If Terminal says the tools are already installed, carry on. Check them with:

```sh
git --version
python3 --version
```

Both should print a version. Python must be 3.9 or later.

## 3. Download and install Garrick

On the [Garrick repository page](https://github.com/iamvenuti/garrick), choose **Code**, then **Download ZIP**. Safari usually unzips the download for you, so look in Downloads for a folder called **garrick-main**. If you see only `garrick-main.zip`, double-click it to unzip it. If you have a guided session booked, stop here and answer the installer questions with your facilitator.

For self-guided setup, run these commands in Terminal. If Finder gave the downloaded folder a different name, type `cd ` and drag that folder into Terminal to supply its path.

```sh
cd ~/Downloads/garrick-main
python3 install.py
```

macOS may ask whether Terminal may access files in your Downloads folder. Click **Allow**: the installer runs from there, and puts the workspace itself in your home folder.

Accept `~/Garrick` as the workspace folder unless you have a reason to choose another. Start with the zones and parties you need for your first project. You can add more later by asking the assistant; for a zone it runs the command in [Another zone](getting-started.md#another-zone). A wall is an explicit pair of parties whose information must stay apart. Two folders alone do not create one. [Getting started](getting-started.md#install) explains the questions.

You can close Terminal when installation finishes. The assistant runs the tools for everyday work, and asks you to approve commands as your app settings say. [The commands it asks to approve](#the-commands-it-asks-to-approve) explains them.

## 4. Open the workspace in your app

Follow just the section for the assistant you chose. Select the **installed workspace**, normally `~/Garrick`, rather than the downloaded `garrick-main` source folder.

### Using Claude

Open Claude and sign in. Under **Settings > Privacy**, review **Help improve Claude** and turn it off before using confidential material on a personal account. This controls training use; it does not make the assistant run offline. See [Claude's desktop guide](https://code.claude.com/docs/en/desktop) for current app behaviour.

![The Claude app's Code tab, with steps 1 to 4 marked in red: the Code tab at the top, New in the sidebar, then Local and the Garrick folder above the box where you type. Below the box the mode reads Auto, which step 5 changes to Accept edits.](assets/desktop-code-tab.png)

1. Click the **Code** tab, `</>`, at the top of the Claude window. The speech-bubble tab beside it is ordinary chat, which can't see your files.
2. Click **+ New** at the top of the left sidebar. The choices below can only be made before a session's first message, so always start from New.
3. Above the box where you type, click the first button and choose **Local**. It runs Claude on your Mac with your own files. The other choices run somewhere else and don't see your workspace.
4. Click the folder button beside it and choose your `Garrick` folder (Command, Shift and H jumps to your home folder). Choose the whole folder, not a zone inside it: the rules and skills live at its top. The button then reads **Garrick**, as in the picture.
5. Below the box, next to the microphone, click the mode and choose **Accept edits**. The picture shows **Auto**; change it. With Accept edits, Claude writes and updates your notes without asking each time, and still asks before running anything else, such as saving to git. The app remembers this for the folder.
6. Ask “Read the workspace instructions and tell me which folder I have open.” On a new workspace, no projects exist yet; continue with [Your first useful session](first-session.md).

Two things to leave alone. Don't turn on "Allow bypass permissions mode" in Settings, which lets Claude run anything without asking. And if the app suggests creating a `CLAUDE.md`, don't: Garrick's instructions live in `AGENTS.md`, and a `CLAUDE.md` in the folder makes Claude stop reading them.


### Using Codex instead

Open the ChatGPT desktop app and sign in to the account and workspace you chose. Use [OpenAI's app guide](https://learn.chatgpt.com/docs/app) if its labels differ from the screenshot.

**Set it up for private work (once).** In ChatGPT, open **Settings**, then **Data Controls**, and turn **Improve the model for everyone** off. On a personal plan it covers Codex as well. Codex's own settings have a separate switch about training on full environments: turn that off too.

![The Codex mode of the ChatGPT app, creating a project: Codex chosen at the top of the sidebar, the project named Garrick, and the Garrick folder added as its source folder on this computer.](assets/codex-app-project.png)

1. At the top of the sidebar, click the mode name and choose **Codex**.
2. Above the box where you type, click **Choose project** and create a new project.
3. Name it `Garrick`. Under **Source folders**, click **Add folder** and choose your `Garrick` folder, the whole folder, not a zone inside it. Leave **This computer** selected: it runs on your Mac with your own files.
4. Click **Create project**.
5. The setting below the box (**Approve for me** in the picture) decides what Codex does without asking you. Click it and choose the setting whose description says Codex works inside your workspace on its own but asks before it runs commands outside the workspace or reaches the internet. It is the closest match to Accept edits in Claude. The names of these settings change between versions, so go by the description. If none fits, choose the one that asks more often.
6. Ask “Read the workspace instructions and tell me which folder I have open.” On a new workspace, no projects exist yet; continue with [Your first useful session](first-session.md).

### The commands it asks to approve

Whichever assistant you use, a first session asks you to approve around fifteen commands. Each shows a line you may not be able to judge, but most are Garrick's own tools, or git saving history on your Mac:

| A command that starts with | Does this |
|---|---|
| `python3 System/tools/scaffold.py` | Makes a zone, project or thread folder from its template |
| `python3 System/skills/intake/intake.py` | Reads what waits in an inbox and files it where it belongs |
| `python3 System/skills/meetings/ingest.py` | Files a conversation in the Meetings wiki |
| `python3 System/tools/check.py` | Runs the workspace check. It changes nothing |
| `git -C Zones/…` or `git -C Wikis`, then `status`, `diff`, `log`, `add` or `commit` | Looks at, or saves, what changed in a zone's or a wiki's history, on your Mac |

None of these sends anything off your Mac. Read the whole line before you approve it, not only its start. With git, the folder after `-C` says only where the command works; the word after the folder says what it does. A git command with `push`, `pull`, `fetch`, `clone` or `remote` reaches the internet, and one with `reset`, `checkout`, `restore`, `clean`, `rm` or `--force` can throw work away. A first session needs none of them: decline them unless you asked for one. Read anything else before you approve it too, above all a command that reaches the internet or works outside your Garrick folder.

You can allow some of these once rather than every time:

- **Claude.** For Garrick's own tools, the `python3` lines above, choose the answer that stops it asking again, rather than the one that allows it this time only. That answer names the start of the command, such as `python3 System/tools/scaffold.py`, and holds for this folder alone. From then on, commands that start the same way run without asking. For git, do the same only when the start it names includes one of the five words above, such as `git -C Zones/Work commit`. If it names only the folder, `git -C Zones/Work`, allow the command this time only: a rule that stops at the folder lets every git command run there without asking, `push` included.
- **Codex.** The setting from step 5 decides. With one that lets Codex work inside the workspace on its own, it runs the tools without asking. If it still asks before each git commit, read the line, then approve it when it is one of the five above: those only look at or save history on your Mac.

## 5. Do one useful piece of work

Follow [Your first useful session](first-session.md). Create one project, file a short conversation and ask for a brief. Finish by saying “wrap it”, then open a fresh chat in the same folder and ask what comes next.

A blank workspace will have nothing useful to say to “what's open” until you create that first project. A few typed call notes are enough; connecting your inbox can wait.

## 6. Add voice or another convenience later

Type or use dictation first. In Claude, the microphone lets you dictate a prompt. In Codex, use **Start voice chat** if offered by your account and app. Voice chat and dictation are different: dictation enters text; a voice chat also lets you hear replies. [OpenAI's voice guide](https://learn.chatgpt.com/docs/features/voice) describes availability. Mac dictation is available under **System Settings > Keyboard > Dictation**.

Once the workflow works at your desk, [phone access](extras/phone-access.md) can let you ask about your work while the laptop stays at home. [Extras](extras/index.md) also covers browsing in Obsidian and selected-mail intake. None is part of this initial setup.

## If something goes wrong

- **The assistant cannot see your work:** check the selected folder. It must be the installed Garrick workspace and the session must run on this computer.
- **Claude does not follow the workspace instructions:** check for a `CLAUDE.md` inside or above the workspace. Ask the assistant to run the workspace check; do not remove an existing file without understanding what uses it.
- **The Code tab or Codex is unavailable:** check the current plan and workspace access with the provider or your administrator.
- **A command fails:** copy its error into your app or show it to the facilitator. Do not repeat installation into a partly created workspace without checking it first.
- **Reporting a problem:** say which Garrick you have. `python3 System/tools/check.py --version`, run in the workspace, prints one line with the version it was installed from and how many of the files Garrick wrote you have changed since, as a count, never their names; put it in the report, or read it to the facilitator.
