# Extra: the zone guard, a hook for Claude Code and Codex

You open a session in one thread, the talk goes somewhere else, and a few turns later the assistant is editing a file in another project, another zone or `System/`. Nothing was wrong with the edit except where it was made: the session that changed it isn't the one that will remember it. `System/rules.md` already says to stop and ask before writing outside the session's project. The zone guard makes sure the question gets asked.

It is optional. Core Garrick never depends on it, and the rule stands without it.

## What it does

A session belongs to the project it was opened in: the folder at `Zones/<Zone>/<Project>`, whichever thread below it you started in. Before the assistant writes a file, the guard looks at where the file is:

- **Inside the session's project**, or loose in its zone's folder (the zone's `Todo.md`): the edit goes ahead.
- **In the Meetings wiki**: the edit goes ahead, from whichever session. Every zone files its conversations there, and `System/rules.md` says that filing a conversation for a project you can name authorises the writes filing needs, the wiki page among them. Stopping that one would put a permission question in the middle of the workflow the rules had just said needs none.
- **Anywhere else in the workspace**, meaning another project, another zone, the Knowledge wiki or `System/`: the edit stops once, with a sentence naming both places, such as *this session was opened in Work › Acme Review, and this edit is in System (System/tools/check.py)*.
- **Outside the workspace** (a scratch folder, `/tmp`, the assistant's own memory): the edit goes ahead.

A path is judged by where it really leads. A link inside the project to a folder in another zone counts as that zone, and on a disk that ignores case, as a Mac's does unless formatted otherwise, `zones/work` and `/users/...` count as `Zones/Work` and `/Users/...`.

A session opened at the workspace root is never stopped, since it belongs to no project, and neither is one opened in `System/`, which governs every zone and wiki. A session opened in a zone's folder may write anywhere in that zone, and one opened in a wiki anywhere in that wiki. The Meetings wiki, as above, is open to every session; the Knowledge wiki is not.

How each assistant stops:

- **Claude Code** asks you in its own permission prompt. Allow it, and the rest of the session writes to that place without asking again. Refuse, and it asks again next time.
- **Codex** hooks can't ask you, so the first edit to a place is refused, with the same sentence telling the assistant to check with you. The next edit there goes through for the rest of the session, whether you said yes or not: the refusal is what makes the assistant ask, and your answer is what decides.

It covers the file-editing tools: Edit, Write, MultiEdit and NotebookEdit in Claude Code, and `apply_patch` in Codex. A shell command that writes a file isn't covered; the rule in `System/rules.md` is what covers that. A scheduled job runs with `GARRICK_HEADLESS=1` and has nobody to ask, so the guard stands aside for it. It reads files only and never calls a model. If anything goes wrong inside it, the edit goes through: a broken guard never stops work.

**What is and isn't enforced.** The guard is a reminder, not a gate: it records nothing about your answer. Because it stands aside for the Meetings wiki, a stray write to a meeting page from the wrong session goes unremarked; that is the price of leaving the guard and the rules saying the same thing about a filing, and the rule in `System/rules.md` is what covers it. In Claude Code the question reaches you through the assistant's own permission prompt, which is where your consent belongs. On the Codex path the refusal only makes the assistant ask you, and a second attempt at the same place goes through whether you said yes or not. A shell command that writes a file isn't covered, and a guard that breaks lets the edit through. So what the guard gives you is the question, asked at the moment it matters; what keeps the work in the right place is the rule in `System/rules.md` and your answer to it.

## Load it

It needs `python3`. Point both assistants at `extras/hooks/zone_guard.py` in the Garrick download you keep. The path may start with `$HOME`, `${HOME}` or `~`, as your assistant reads it: Settings and the update read it the same way, and a path that is still not a full path is left out. Settings trusts a hooks folder only where it holds Garrick's own `zone_guard.py` and `read_guard.py` as this release ships them, and never looks for them inside your workspace. When you replace that download with a newer one, the next session uses the new copy. The update command does not change it, since it lives outside your workspace, but its report names the guard when the copy your settings point at differs from the newer Garrick's.

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

To see whether it is loaded, without changing anything:

```sh
python3 /path/to/garrick/extras/hooks/zone_guard.py --check
```

It reads `~/.claude/settings.json` and `~/.codex/hooks.json` and says, for each assistant, whether the guard runs on the events above, for every editing tool, from a `zone_guard.py` that exists. A guard you moved, or a matcher that names `Edit|Write` and leaves out the other two, is named. An assistant with no folder in your home is skipped. It exits 0 when every assistant found has the guard, and 1 when one does not or none was found. It cannot see whether Codex trusts the hook: run `/hooks` in Codex for that.

To run its tests, from the repository:

```sh
python3 -m unittest discover -s tests -p test_zone_guard.py
```

## The read guard

**Turn it on in Garrick.app.** Open Settings, then Walls, then *Read guard*, and choose Watch only or On. Garrick registers the hook in your assistant's settings for you, from the Garrick you keep (it finds the copy beside the zone guard your assistant already runs, so register the zone guard first), checks it the way `read_guard.py --check` does, and says so. Off takes the registration out. The same rows set *Across a wall* (Refuse or Ask me) and the two tool lists. [The read guard](../../docs/read-guard.md) explains the choices and how to use the first week. What follows is the registration by hand, for a computer without the app, and the details the page keeps behind it.

`read_guard.py` is the zone guard's counterpart for reads (#613), and for what a mail or calendar connector hands back (#614). It is optional, and it ships warn-only: it decides, logs and lets everything through until `System/garrick-settings.json` says `"read-guard": "enforce"`. [What is enforced](../../docs/enforced.md#the-read-guard) says what it covers, what it cannot, and what it logs. Its settings, all in that file:

| Key | Values | Default |
|---|---|---|
| `read-guard` | `warn`, `enforce` | `warn`; anything else, or an unreadable file, is `warn`. The connector filter alone reads a file that is there and does not read as `enforce`, since it cannot tell it was not On |
| `read-guard-cross-zone` | `deny`, `ask` | `deny`; `ask` raises Claude Code's permission prompt for a read across a wall |
| `connector-tools` | a list of tool name patterns | the Gmail and Calendar patterns |
| `connector-tools-skip` | a list of tool name patterns | none: tools you use that return nothing a party can label, so `check.py` stops naming them |

The zone guard also refuses, in every mode, a session's write into the read guard's own folder (where its log and scope records are kept), and the read guard refuses a session's read of it once enforcing; each hook computes the folder the same way, and a test holds the two to one answer. When the filter cannot read the Parties table, or the intake script that matches an address, it cannot tell which result belongs where: On, every result of a listed tool is replaced by the wall sentence; Watch only (`warn`), nothing is removed and the log gets one `undecided` line. A connector result is read whole: every list in it is filtered, what is left beside the lists is judged as one more result, and no count stays once anything is removed.

It needs `python3` and the workspace's own `System/tools`. Point both assistants at `extras/hooks/read_guard.py` in the Garrick download you keep, as for the zone guard.

**Claude Code**: add to the `hooks` block of `~/.claude/settings.json`, beside the zone guard's entries:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/read_guard.py", "timeout": 5 }] }
    ],
    "PreToolUse": [
      {
        "matcher": "Read|Grep|Glob|Bash",
        "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/read_guard.py", "timeout": 5 }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "mcp__.*",
        "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/read_guard.py", "timeout": 5 }]
      }
    ]
  }
}
```

The `PostToolUse` entry is the connector filter. It is registered for every connector tool, so the guard can note which ones the session used; only the tools on the `connector-tools` list are filtered.

**Codex** (0.124 or later; trust it in `/hooks`, since Codex skips a hook until you do, and again after any change to it, as when Settings changes the registration): add `SessionStart` and a `PreToolUse` with the matcher `Bash` to `~/.codex/hooks.json`, with the same command. Codex gets no connector hook: it cannot replace a tool's output.

`python3 read_guard.py --check` says whether it is registered, and `python3 zone_guard.py --check` reports it beside its own line, without changing its exit code. Its tests: `python3 -m unittest discover -s tests -p "test_read_guard.py"`, and `test_connector_guard.py` for the filter.

## The waiting hook

`waiting_hook.py` is a second, separate hook, for Claude Code only. A permission prompt is not written to the transcript, so Garrick cannot tell from it that a session is stopped on one. The hook runs on `Notification`, `UserPromptSubmit` and `PostToolUse`. On a `permission_prompt` or an `idle_prompt` notification it writes a small marker for the session, `~/.garrick-waiting/<session id>.json`, holding the kind, the tool's name where the prompt names one, and the time. Nothing else from the event is kept: the message can name a file, a command or a question. The next prompt removes the marker, and so does the result of the tool the prompt was for; the result of another tool does not, and an idle prompt never replaces an open permission prompt. The Overview's [Waiting on you now](../../docs/extras/status-page.md#waiting-on-you-now) card reads it; only a `permission_prompt` makes a session wait. The marker is outside every workspace and never committed. Without the hook, a session on a permission prompt shows as working, and a question it asks with `AskUserQuestion` still shows as waiting.

Add it to the `hooks` block of `~/.claude/settings.json`, beside any others, for each event:

```json
{
  "hooks": {
    "Notification": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/waiting_hook.py", "timeout": 5 }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/waiting_hook.py", "timeout": 5 }] }],
    "PostToolUse": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/waiting_hook.py", "timeout": 5 }] }]
  }
}
```

Its tests: `python3 -m unittest discover -s tests -p test_waiting_hook.py`.

## The parked-thread hint

`parked_hint.py` is a third, separate hook, for Claude Code only (#664). Parking a thread moves its memory pointer out of the memory index until the thread wakes, so the session no longer sees a line about it and cannot notice that a request is about it. The hook gives that back. It runs on `UserPromptSubmit`, reads the prompt, and matches its whole words, in any case, against each parked thread's name, its `spoken:` form, its hub's `party:` tag and the names of that party's people. One word of a name or spoken form is enough when it has four letters or more and is not a common one such as "plan" or "note"; a party tag or a person's full name matches as a phrase. At most the best two threads are named, the most matched words first. On a match it adds one line to the session's context: *This may belong to Acme, Pricing, which is parked: say 'wake Acme, Pricing' to pick it up.* With no match it adds nothing.

- **It does nothing without the `memory` setting** in `System/garrick-checks.json`, since without it no pointer ever left an index. It does nothing outside a workspace, and nothing on any error.
- **Walls.** A session in a zone, or in a project of it, is told of that zone's parked threads and of an open zone's. A session at the workspace root or in `System/`, which the zone guard treats as belonging to no zone, is told of any zone's. A session in a wiki, or anywhere else, is told of open zones only. A parked thread of another walled zone is never named, and nothing says that one exists, not even a count.
- **Cost.** It lists the hub and thread notes by name and reads their frontmatter, never the notes' bodies, and only when a note's modification time has changed. What it reads is kept in `System/generated/parked-hints.json`, which git leaves out: names, zones, statuses, spoken forms, party tags and the names of those parties' people. It writes nothing of the prompt anywhere, in the cache, in a log or in an error. It ends in well under the 5 seconds the registration allows.

Add it to the `hooks` block of `~/.claude/settings.json`, beside any others:

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/garrick/extras/hooks/parked_hint.py", "timeout": 5 }] }]
  }
}
```

The installer does not write this line: like the waiting hook's, it lives in your home folder, outside the workspace, and you choose to add it. Its tests: `python3 -m unittest discover -s tests -p test_parked_hint.py`.
