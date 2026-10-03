# Try it safely

You don't have to commit to anything to see how this works.

## Install into a new folder

```sh
python3 examples/demo/build.py --target ~/Garrick-demo
```

Run it from the folder you downloaded Garrick into. It builds, at `~/Garrick-demo`, the workspace of a fictional advisor about four weeks into real use: Sam Rivera, two clients who compete, a wall between them, a carrier that works for both, a few projects with their threads, a month of filed meetings, and one call and a few emails still waiting to be filed. Run `cd ~/Garrick-demo`, start Claude Code or Codex there, and try "what's open", "open supplier map", "process the inbox" or "prep me for Cobalt" from inside a Birch thread. [The demo's README](../examples/demo/README.md) describes the world. It is a real workspace; only the people in it are invented.

To start from an empty workspace instead, with only the demo's parties and walls filled in, run `python3 install.py --config examples/acme.json --target ~/Garrick-empty` and follow [Your first project](getting-started.md#your-first-project).

## Nothing in your home config is written

The installer writes only inside the target folder you gave it. It checks every path before writing to it and refuses to write anywhere else. It won't touch `~/.claude`, `~/.codex`, or anything under your home folder outside the target: no global settings changed, no config files edited, nothing installed system-wide. The `.claude/skills` and `.agents/skills` folders it creates are symlinks inside the workspace itself, pointing back at that workspace's own `System/skills`, not at anything in your account-level config.

It also refuses certain targets outright: your home folder itself or any folder above it; anywhere under `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Library`, because macOS blocks scheduled jobs from reading those folders regardless of what you intend to run there; and the folder Garrick came in, anywhere inside it, or a folder holding it, so your workspace and the download never mix.

## Your existing setup is untouched

If you already have Claude Code or Codex configured, a Garrick install changes none of it. Your existing projects, your existing settings, your existing skills: none of them are read, moved, or referenced. A demo workspace at `~/Garrick-demo` and a real one at `~/Garrick` (or wherever you choose) sit side by side with nothing shared between them except the version of the assistant you're running.

## Remove it by deleting the folder

```sh
rm -rf ~/Garrick-demo
```

That's the whole uninstall. Everything the install created, the workspace, its git repositories, the symlinks, lives inside that one folder, so deleting it leaves no trace anywhere else on the machine.

## One honest caveat

Claude Code and Codex each keep their own session history, in their own folders, outside any workspace: conversation transcripts, cached state, whatever their harness stores for itself. Deleting `~/Garrick-demo` removes the workspace and everything it holds, but it does not clear that history. If you want no record anywhere that you tried this, you'd need to clear the assistant's own session data separately, the same way you would for any other project you'd asked it to work on.
