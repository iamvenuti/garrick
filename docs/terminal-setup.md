# Terminal setup

Use this route if you are comfortable with commands and want to choose your own tools. Claude Code or Codex CLI can run Garrick without a provider's desktop app. Obsidian and cmux are optional additions.

Prefer an app window? Use [Desktop first steps](first-steps.md). The two routes share the same workspace and can be used on different days.

## Prepare the Mac

You need git, Python 3.9+ and one assistant CLI. If git or Python is missing, install Apple's Command Line Tools with `xcode-select --install`, then check `git --version` and `python3 --version`.

Install and sign in to either [Claude Code](https://code.claude.com/docs/en/setup) or [Codex CLI](https://learn.chatgpt.com/docs/cli), following that vendor's current instructions. Garrick expects Claude Code 2.1.277 or later for native `AGENTS.md` loading. Use an account approved for the material you will process and review the provider's data settings.

## Try the demo, then install your own

```sh
git clone https://github.com/iamvenuti/garrick.git ~/garrick-source
cd ~/garrick-source
python3 examples/demo/build.py --target ~/Garrick-demo
```

In another terminal:

```sh
cd ~/Garrick-demo
claude
```

Or run `codex` in that folder. Say “what's open”, then try the [fictional wall exercise](first-session.md#try-the-wall-with-fictional-data).

Back in `~/garrick-source`, run:

```sh
python3 install.py
```

Start your assistant in the folder it creates (`~/Garrick` by default). Follow [Your first useful session](first-session.md). [Getting started](getting-started.md) documents config files, scaffold commands, adding a zone, repository boundaries and the checks.

The first session asks you to approve the workspace's own scripts and git. [The commands it asks to approve](first-steps.md#the-commands-it-asks-to-approve) lists what each does. In Claude Code, answer the prompt with the option that stops it asking again for that command in this folder. In Codex, choose an approval setting that lets it work inside the workspace without asking, and still asks before it reaches the internet or works outside the folder.

## Add tools when useful

| Need | Optional tool | How it relates to Garrick |
|---|---|---|
| Browse notes and backlinks yourself | [Obsidian](extras/obsidian.md) | Opens the same Markdown files. It does not enforce confidentiality boundaries. |
| Work on several threads side by side | [cmux](extras/cmux.md) | Runs separate terminal sessions. Ask each assistant to open the corresponding Garrick thread. |
| Ask about your work from your phone | [Phone access](extras/phone-access.md) | Connects to an assistant running on the computer that holds your files. Requirements differ by provider. |
| Save selected mail into the inbox | [Ways in](extras/ways-in.md) | Adds fetching once manual filing is useful. |

A typical terminal setup is Claude Code or Codex inside cmux, with Obsidian open for reading. You can also use a plain terminal and any text editor.

For **Codex remote voice on iPhone**, add the ChatGPT desktop host app and pair the phone with it. Your CLI workflow can remain your everyday route; open the same Garrick folder in the app and resume from its notes. Do not assume a CLI conversation appears in the app automatically. **Claude Code Remote Control** can instead run from a terminal without the Claude desktop app. The [phone guide](extras/phone-access.md) covers both.
