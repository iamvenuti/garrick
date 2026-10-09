# Extra: a desktop toolkit around the workspace

A Garrick workspace is folders of Markdown and an assistant that works in them. A few ordinary Mac apps make that easier to live with day to day. Garrick installs none of them and depends on none of them. Each slot below names what it does for the workspace, what to look for, and the app its author uses. Any app that fills the slot will do.

## Opening a Markdown file

Notes, thread notes and deliverable drafts are `.md` files, and macOS opens them as plain text unless you tell it otherwise.

- **A default app for `.md`.** Pick an editor that shows Markdown rendered, so a double-click in Finder opens a note readable. The author uses [Typora](https://typora.io). [Obsidian](obsidian.md) can be the default too, but it opens the whole vault around one file.
- **A preview in Finder.** A Quick Look extension renders a `.md` file when you press the space bar on it, without opening anything. The author uses [QLMarkdown](https://github.com/sbarex/QLMarkdown), which is open source. Turn its extension on once in System Settings.
- **A plain-text editor** for the config files, such as `.json`, where rendering gets in the way. Any will do. The author uses [CotEditor](https://coteditor.com).

## Dictation

Garrick is built to be spoken to: its rules name short phrases such as "open X" and "wrap it". Speaking is faster than typing for most prompts, and the assistant reads through the odd misheard word.

- **macOS dictation** is built in and enough to start with.
- **A dictation app** helps once you dictate most prompts. Look for one that transcribes on your Mac, so the audio never leaves it, and that lets you paste into any app with a hotkey. The author uses [VoiceInk](https://github.com/Beingpax/VoiceInk), which is open source and transcribes locally.

Some dictation apps can also send the transcribed text to a cloud model to clean it up. That step sends what you said, including anything confidential, to that model's provider before it reaches your assistant. Decide whether you want it, and turn it off for work whose confidences you hold.

Names get mangled more than anything else. Put the ones your dictation gets wrong in `System/context.md`, so the assistant recognises them, and in your dictation app's own vocabulary, if it has one, so they arrive right.

## Watching your usage

Plans for Claude and Codex have limits, and a long session or a scheduled job can use more than you expect. A small monitor that shows how much of the limit is used saves a surprise halfway through a task. The author uses [Codenotch](https://github.com/vinzdg/codenotch), which pins a small notch to a screen edge, with a ring per assistant, and shows whether each session is working or waiting for you.

## What you lose without them

Nothing that Garrick does. The workspace installs, opens and wraps threads, and checks itself the same way. Without a Markdown app you read notes in Obsidian, your assistant or a text editor. Without a dictation app you type, or use the built-in dictation. Without a usage monitor you find out about a limit when you reach it.
