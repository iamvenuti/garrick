# Extra: phone access

Garrick doesn't provide, or need, its own way to reach a workspace from a phone. Since a Garrick workspace is nothing more than files under git, whatever remote or mobile feature you already use to run Claude Code or Codex from a phone works against it unchanged: there's nothing Garrick-specific for a remote client to support.

## What's available today

- **Claude Code Remote Control** and **Codex Remote** (in the ChatGPT app) are first-party: each lets you continue a session that's running on your machine from that assistant's phone app. Check each vendor's documentation for the current setup.
- **Third-party clients** built against either assistant's session protocol are another route, if you'd rather not use the first-party app; check what each one does with your data and whether it needs its own account or relay before trusting it with a workspace that holds other people's confidences.

Whichever you use, it's the assistant's session running against your workspace exactly the way it would from a terminal; the zones, the walls, the resume points, all behave the same, because none of that logic lives in the terminal, it lives in the files the session is reading.

## What it adds

The ability to say "open Acme pricing" from a phone and get the same two-sentence answer you'd get at your desk, without carrying a laptop everywhere.

## What you lose without it

Nothing about the workspace. You lose the convenience of reaching it away from your machine, not any of its behavior; everything in `docs/getting-started.md` and `docs/principles.md` works the same whether the session is local or remote.
