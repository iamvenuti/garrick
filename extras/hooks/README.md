# Extra: the zone guard, a hook for Claude Code and Codex

You open a session in one thread, the talk goes somewhere else, and a few turns later the assistant is editing a file in another project, another zone or `System/`. Nothing was wrong with the edit except where it was made: the session that changed it isn't the one that will remember it. `System/rules.md` already says to stop and ask before writing outside the session's project. The zone guard makes sure the question gets asked.

It is optional. Core Garrick never depends on it, and the rule stands without it.

## What it does

A session belongs to the project it was opened in: the folder at `Zones/<Zone>/<Project>`, whichever thread below it you started in. Before the assistant writes a file, the guard looks at where the file is:

- **Inside the session's project**, or loose in its zone's folder (the zone's `Todo.md`): the edit goes ahead.
- **Anywhere else in the workspace**, meaning another project, another zone, a wiki or `System/`: the edit stops once, with a sentence naming both places, such as *this session was opened in Work › Acme Review, and this edit is in System (System/tools/check.py)*.
- **Outside the workspace** (a scratch folder, `/tmp`, the assistant's own memory): the edit goes ahead.

A session opened at the workspace root is never stopped, since it belongs to no project. A session opened in a zone's folder may write anywhere in that zone, and one opened in a wiki anywhere in that wiki.

How each assistant stops:

- **Claude Code** asks you in its own permission prompt. Allow it, and the rest of the session writes to that place without asking again. Refuse, and it asks again next time.
- **Codex** hooks can't ask you, so the first edit to a place is refused, with the same sentence telling the assistant to check with you. Once you say yes, the next edit there goes through for the rest of the session.

It covers the file-editing tools: Edit, Write, MultiEdit and NotebookEdit in Claude Code, and `apply_patch` in Codex. A shell command that writes a file isn't covered; the rule in `System/rules.md` is what covers that. A scheduled job runs with `GARRICK_HEADLESS=1` and has nobody to ask, so the guard stands aside for it. It reads files only and never calls a model. If anything goes wrong inside it, the edit goes through: a broken guard never stops work.

## Load it

It needs `python3`. Point both assistants at `extras/hooks/zone_guard.py` in the Garrick download you keep. When you update Garrick, the next session uses the new copy.

**Claude Code**: add both events to the `hooks` block of `~/.claude/settings.json`, keeping any hooks already there:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/zone_guard.py", "timeout": 5 }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/zone_guard.py", "timeout": 5 }]
      }
    ]
  }
}
```

The second one is how it remembers a place you allowed. Sessions started after the change use it.

**Codex**: add it to `~/.codex/hooks.json` (Codex 0.124 or later), then run `/hooks` in Codex and trust it. Codex skips a hook until you do, and again after any change to it.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/zone_guard.py", "timeout": 5 }]
      }
    ]
  }
}
```

To stop using it, remove the entries.

## Check it

From the repository:

```sh
python3 -m unittest discover -s tests -p test_zone_guard.py
```
