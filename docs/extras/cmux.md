# Extra: cmux, one terminal tab per thread

This is an optional extension of the [terminal route](../terminal-setup.md). Run Claude Code or Codex CLI inside it; no provider desktop app is required for local work. [Phone access](phone-access.md) is a separate matter, and what it needs differs by provider.

Garrick's own idea of a thread, one line of work with one resume point, doesn't care how many terminal windows you have open, or whether you have any open at all beyond the one you're typing in. cmux is a terminal built for running several agent sessions side by side, one per tab, which maps cleanly onto Garrick's model: a tab for each thread you are working on.

Garrick ships nothing that talks to cmux directly. There's no bundled skill or config for it in `System/skills`; using it is a matter of opening one cmux tab per active thread, in the zone folder that thread lives in, the same way you'd open one plain terminal tab per thread without it.

## How to use it

Run cmux against the workspace the way you'd run it against any repository: one tab per thread you're actively working, started in that thread's folder or its zone's, then "open [thread]" to the assistant inside it. The thread's `### Resume here` block, not the terminal session, is what tells you and the assistant where the work stands.

## When cmux brings its tabs back

cmux can restore its tabs after a restart, but the assistant does not always come back inside them. In testing, Claude Code came back in some tabs while others opened at a bare prompt, and Codex did not come back in any. Where a tab has no assistant, start it again with that assistant's own resume command, typed in the tab's folder:

- Claude Code: `claude --resume <id>`, or `claude --continue` for the most recent conversation.
- Codex: `codex resume <id>`, or `codex resume --last`.

Each command brings back only that assistant's own conversations. Whatever came back, say "open [thread]": it rebuilds the context from the thread's resume point, so a fresh session loses nothing the work depends on.

## What it adds

A sidebar of live sessions instead of juggling terminal tabs by hand, and a CLI you can script against if you want to automate opening a set of tabs for the threads you work most often.

## What you lose without it

Nothing about Garrick itself. One thread at a time, in whatever terminal or terminal tab you already use, works exactly the same: the resume point lives in the thread note, not in cmux's session state, so closing a plain terminal and opening a new one loses you nothing that "open [thread]" doesn't put straight back in front of you.
