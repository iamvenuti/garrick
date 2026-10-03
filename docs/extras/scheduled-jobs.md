# Extra: scheduled jobs

Nothing in core Garrick runs on its own. There's no cron entry, no launchd job and no background process installed by `install.py`. Running the check, wrapping a thread, filing a meeting: all of it happens because you or your assistant did it in a session.

Two kinds of thing can run on a schedule, and they need different amounts of care:

- **A script**, such as `System/tools/check.py` or the [mail fetcher](ways-in.md). It does the same thing every time and calls no assistant.
- **An assistant**, given a prompt and nobody to answer its questions. `extras/jobs/` holds what that needs: a runner, a wrapper, a spend ledger with caps, for Claude, a profile that denies the sending, sharing and deleting tools it names, and one example job.

## A script on a schedule

On macOS, a launchd agent is the usual way to run something without a terminal open. A plist that runs `/usr/bin/python3 /Users/<you>/Garrick/System/tools/check.py --json` once a day is the smallest version. launchd does not expand `~` or start in your workspace, so every path in the plist is spelled out in full. This is also why the installer refuses a workspace under `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Library`: macOS stops a scheduled job from reading there. The check fixes nothing on its own; it tells you sooner that something needs fixing. The fetcher, `extras/fetch/imap_fetch.py --config <file>`, runs the same way every few minutes, and only saves mail into a zone's inbox: sorting it still waits for you to say "process the inbox".

## An assistant on a schedule

| File in `extras/jobs/` | What it does |
|---|---|
| `agent.py` | Runs one assistant turn. Every job calls it instead of naming `claude` or `codex` |
| `job.py` | Wraps one scheduled run: log, heartbeat, lock, watchdog, sign-in check, idle alarm |
| `headless-settings.json` | The deny list every unattended Claude call loads |
| `whats_open.py` | The example job: a "what's open" brief per zone, written outside the workspace |
| `launchd/garrick.whats-open.plist` | The example job on a schedule, every morning at 06:30 |

### Set it up

1. **Copy `extras/jobs/` into your workspace as `System/jobs/`**, and commit it in the workspace root's repository. The jobs then travel with the workspace, and, for Claude, the deny profile refuses any edit to them.
2. **Run the example once by hand**, from the workspace:
   ```sh
   python3 System/jobs/job.py whats-open --agent --cwd ~/Garrick -- \
     python3 System/jobs/whats_open.py --workspace ~/Garrick --zone Work
   ```
   The brief lands in `~/Library/Logs/garrick-jobs/briefs/`, with the log and the heartbeat beside it.
3. **Schedule it.** Copy `System/jobs/launchd/garrick.whats-open.plist` to `~/Library/LaunchAgents/`, replace every `<you>` with your macOS user name, and load it with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/garrick.whats-open.plist`. Set `GARRICK_HARNESS` in the plist to `claude` or `codex`.
4. **See what it did**: `python3 System/jobs/agent.py ledger` lists the last 24 hours of calls, by job, with their cost and any tool the assistant was refused.

The example reads one zone per assistant call, so no single turn ever holds two zones, and writes one brief per zone outside the workspace. A zone with nothing open costs no call.

### What an unattended assistant may do

With nobody watching, a job gets the least it needs, and Claude is denied the ways out of the machine that the profile names.

- **An allow list per call.** A job names the tools it needs: `--allow Read`, `--allow Grep`. Claude refuses other tools, with one exception: the runner accepts file edits (`--permission-mode acceptEdits`), so a job can change files outside `System/` unless its prompt keeps it from doing so.
- **A deny list on every call.** `headless-settings.json` denies sending, replying, forwarding, sharing and deleting through the Gmail, Google Calendar, Google Drive and Notion connectors, as claude.ai names them; publishing; network and shell tools such as `curl`, `ssh`, `git push` and `rm`; and any edit under `System/`, inside `.git/`, or to the assistants' own settings. A deny beats an allow, so a job that lists one of these by mistake is still refused. If you have other connectors, add their sending tools to the list: each is named `mcp__<server>__<tool>`.
- **Only user and project settings.** Each call loads `--setting-sources user,project`. Allow rules you saved for your own sessions in a project's `.claude/settings.local.json` would otherwise apply to the job too. Tested with Claude Code 2.1.287: a job allowed only `Read`, started in a folder whose local settings allowed `python3`, ran `python3`; with `user,project` it was refused. Loading `user` alone goes too far: the job no longer reads the workspace's `AGENTS.md`.

Under **Codex** there is no list of tools to allow or deny. A job runs sandboxed to its working folder, which is its write boundary, and has no connectors unless you have configured them. `agent.py requires <name>` stops a job, with exit 6, when the assistant has no connector it needs.

### What it spends

Every call adds one line to `ledger.jsonl` in the jobs folder: when, which job, assistant, tier, turns, cost, seconds, exit code, and any tool that was refused. Before each call the ledger is read, and the call is refused, with exit 8 and no assistant started, when a limit is reached:

| Variable | Default | Limit |
|---|---|---|
| `GARRICK_CAP_CALLS_DAY` | 48 | calls in the last 24 hours |
| `GARRICK_CAP_CALLS_HOUR` | 12 | calls in the last hour |
| `GARRICK_CAP_COST_DAY` | 20 | dollars in the last 24 hours |
| `GARRICK_MAX_CALL_USD` | 5 | dollars for one Claude call, after which Claude stops |

Set one to 0 to remove it. The cost is Claude Code's own estimate at list prices, so on a subscription it measures how much you use rather than what you pay. Codex reports neither turns nor cost; its lines leave them empty, and only the call limits hold it.

### Write your own job

A job is a script that does the certain part itself and asks the assistant only for judgment.

```python
import sys
sys.path.insert(0, "/Users/<you>/Garrick/System/jobs")
import agent

code, answer = agent.run("sonnet", prompt, allow=["Read", "Grep"], cwd=workspace)
if code != 0 or "SWEEP COMPLETE" not in answer:
    sys.exit(code or 3)        # no closing line: the run did not finish its work
agent.report_items(handled)    # how much it did, for the idle alarm
```

- **Tiers, not model names**: `haiku`, `sonnet` or `opus`. Codex maps each through `GARRICK_CODEX_MODEL_<TIER>`.
- **End the prompt with a closing line to print**, and check for it. A run that stopped early must not look like a run that found nothing.
- **Report how much it handled.** A job that runs cleanly for a week and does nothing gets flagged in its log and heartbeat.
- **One zone per call** when the job reads zone material. The [walls](../principles.md) still apply to anything it writes.
- **Write outside the zones**, or into an inbox for `intake` to sort. A job decides nothing a session would have asked you about.

### Exit codes

| Code | Meaning |
|---|---|
| 3 | The answer came back without its closing line; nothing was written |
| 4 | The assistant could not sign in, twice, five minutes apart; the job did not run |
| 6 | A connector the job needs is missing |
| 8 | A spend limit was reached; nothing was called |
| 75 | The previous run still holds the lock; this one was skipped |
| 124 | The watchdog stopped a run that went past its time limit, 25 minutes by default |

### Limits

- The suite tests the runner, the wrapper, the caps and the example against fake assistants. The deny profile, the settings sources and the ledger's numbers were checked by hand against Claude Code 2.1.287. Codex has not been run end to end through this extra.
- The sign-in check asks the assistant whether it is signed in (`claude auth status`, `codex login status`), with no model call. A scheduled job's access to the login keychain can fail now and then; the check, and its one retry five minutes later, exist for that.
- A laptop that is asleep runs nothing. launchd runs a missed calendar job when the Mac wakes, and several overdue assistant jobs then take turns rather than fail each other's sign-in.

## See them on one page

The [status page](status-page.md) reads the heartbeats, the job logs and the ledger, and shows each job's last two weeks as a strip of days next to everything else in the workspace that needs you.

## What you lose without it

Nothing about correctness. `check.py` catches exactly the same problems whether you run it once a week by hand or a launchd job runs it nightly, and every brief a job writes, you can ask for in a session. The difference is how long a problem sits before you notice it, and whether the first thing you read in the morning is already waiting.
