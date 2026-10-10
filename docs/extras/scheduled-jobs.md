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
| `job.py` | Wraps one scheduled run: log, heartbeat, lock, watchdog, sign-in check, idle alarm, notices |
| `headless-settings.json` | The deny list every unattended Claude call loads |
| `whats_open.py` | The example job: a "what's open" brief per zone, written outside the workspace |
| `launchd/garrick.whats-open.plist` | The example job on a schedule, every morning at 06:30 |

### Set it up

1. **Copy `extras/jobs/` into your workspace as `System/jobs/`**, and commit it in the workspace root's repository. The jobs then travel with the workspace, and the deny profile keeps Claude's file tools from editing them.
2. **Run the example once by hand**, from the workspace:
   ```sh
   python3 System/jobs/job.py whats-open --agent --cwd ~/Garrick -- \
     python3 System/jobs/whats_open.py --workspace ~/Garrick --zone Work
   ```
   The brief lands in `~/Library/Logs/garrick-jobs/briefs/`, with the log and the heartbeat beside it.
3. **Schedule it.** Copy `System/jobs/launchd/garrick.whats-open.plist` to `~/Library/LaunchAgents/` and edit the copy. The plist is XML, so it writes `<you>` as `&lt;you&gt;`: search for that. If your workspace is not `~/Garrick`, first replace each `/Users/&lt;you&gt;/Garrick` with its full path. Then replace every other `&lt;you&gt;` with your macOS user name, and set `GARRICK_HARNESS` to `claude` or `codex`. Load it with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/garrick.whats-open.plist`. If a run fails before `job.py` can write its own log, as it does when a path is left wrong, the error goes to `whats-open.launchd.log` beside that log. launchd does not create the folder, which is why step 2 comes first. If not even that file appears, `launchctl print gui/$(id -u)/garrick.whats-open` shows how launchd last ran the job.
4. **See what it did**: `python3 System/jobs/agent.py ledger` lists the last 24 hours of calls, by job, with their cost and any tool the assistant was refused.
5. **Check your own jobs' scripts** once you write some: `python3 System/jobs/job.py check-scripts ~/Library/LaunchAgents/garrick.*.plist` reads each plist, and each script it runs, for a line that runs `claude -p` or `codex exec` itself. It prints the file and line of each, and exits 1 when it finds one. Such a call loads no deny profile, counts against no cap and works with one assistant only. Name scripts instead of plists to check them directly.

The example reads one zone per assistant call, so no single turn ever holds two zones, and writes one brief per zone outside the workspace. A zone with nothing open costs no call.

### What an unattended assistant may do

With nobody watching, a job gets the least it needs, and Claude is denied the ways out of the machine that the profile names.

- **An allow list per call.** A job names the tools it needs: `--allow Read`, `--allow Grep`. Claude refuses the rest: with nobody to ask, a tool that needs permission runs only when the list names it or your own settings allow it, as below. A job that must write files names the tools for it: `--allow Edit`, `--allow Write`. The runner sets the permission mode to `default` on every call, so a default mode in your own settings, such as accepting edits, does not reach a job.
- **A deny list on every Claude call.** `headless-settings.json` denies sending, replying, forwarding, sharing and deleting through the Gmail, Google Calendar, Google Drive and Notion connectors, as claude.ai names them; publishing; fetching web pages and searching the web; shell commands that start with `curl`, `ssh`, `git push`, `rm` and a few others; publishing a Claude document or starting another agent session; the browser and computer-use servers; and edits by Claude's file tools under `System/`, inside `.git/`, to the assistants' own settings or to your launchd jobs. A deny beats an allow, so a tool on the list is refused even when a job lists it by mistake or your own settings allow it. If you have other connectors, add their sending tools to the list: each is named `mcp__<server>__<tool>`.
- **A core the list must keep.** `agent.py` names, in `CORE_DENY`, the entries no profile may lose: sending, replying and forwarding mail, binning mail and Drive files, making and deleting calendar events, sharing a Drive file, editing a Notion page or commenting on one, and shell commands that start with `curl`, `git push` or `rm`. A profile that lacks any of them is refused like a missing one: exit 64, a line naming what it lacks, and no call. Add to the list freely; take one of these out and every Claude job stops until it is back. Keep them even for a connector you don't use, since a deny costs nothing.
- **The shell rules are best-effort.** Each matches a command by how it starts, so `git -C . push` or `/bin/rm` gets past it, and the edit rules do not cover a shell command that writes a file. A job allowed `Bash` can do whatever a command can: allow it only to a job that needs it.
- **Only user and project settings.** Each call loads `--setting-sources user,project`. Allow rules you saved for your own sessions in a project's `.claude/settings.local.json` would otherwise apply to the job too. Tested with Claude Code 2.1.287: a job allowed only `Read`, started in a folder whose local settings allowed `python3`, ran `python3`; with `user,project` it was refused. Loading `user` alone goes too far: the job no longer reads the workspace's `AGENTS.md`. Allow rules in `~/.claude/settings.json` and in the workspace's `.claude/settings.json` do reach a job; only the deny list overrides them.

Under **Codex** there is no list of tools to allow or deny, and the deny profile does not apply, so the job's allow list chooses the sandbox instead. A job allowed only tools that read (`Read`, `Grep`, `Glob`, `LS`), or nothing, as the example is, runs **read-only**: Codex can write no file, ignores your own Codex configuration (its MCP servers, plugins and hooks), and runs with connectors, plugins, the browser and web search switched off. Codex's sandbox does not govern connectors, so switching them off is what keeps a job that only reads from sending anything. Any other job runs sandboxed to its working folder, which is its write boundary, with the connectors and settings you have configured: a job that files mail needs its mail. Codex's record of each run, the prompt and whatever it read included, goes to `<job>.transcript.log` beside the job's log, and is rotated like the log at 1 MB. `agent.py requires <name>` stops a job, with exit 6, when the assistant has no connector it needs.

### What it spends

Every call adds one line to `~/Library/Logs/garrick-jobs/ledger.jsonl`, beside the jobs' logs: when, which job, assistant, tier, turns, cost, seconds, exit code, and any tool that was refused. The ledger keeps the last 60 days, more than any limit below or the status page needs. Before each call the ledger is read, and the call is refused, with exit 8 and no assistant started, when a limit is reached:

| Variable | Default | Limit |
|---|---|---|
| `GARRICK_CAP_CALLS_DAY` | 48 | calls in the last 24 hours |
| `GARRICK_CAP_CALLS_HOUR` | 12 | calls in the last hour |
| `GARRICK_CAP_COST_DAY` | 20 | dollars in the last 24 hours |
| `GARRICK_MAX_CALL_USD` | 5 | dollars for one Claude call, after which Claude stops and the call exits 8 |

Set one to 0 to remove it. The ledger line also names the model the call used, which the tier alone does not say. The cost is Claude Code's own estimate at list prices, so on a subscription it measures how much you use rather than what you pay. Codex reports neither turns nor cost; its lines leave them empty, and only the call limits hold it.

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

A job written in the shell does the same through `agent.py` on the command line:

```sh
jobs=/Users/<you>/Garrick/System/jobs
out="$(mktemp)"
python3 "$jobs/agent.py" requires gmail || exit $?
python3 "$jobs/agent.py" run --tier sonnet --allow Read --allow Grep \
  --prompt-file sweep-prompt.md --timeout 900 > "$out" || exit $?
grep -qx 'SWEEP COMPLETE' "$out" || exit 3
python3 "$jobs/agent.py" items-from "$out"    # the prompt asked for a line ITEMS <n>
```

`--prompt` takes the prompt itself instead of a file, and with neither it is read from standard input. `--timeout` stops the call, not the job, with exit 124, so a job keeps time for whatever it does after the call; the wrapper's own limit still holds the whole run. `agent.py items <n>` reports a count the script made itself, and `items-from` reports the number from the last line in a file that reads `ITEMS <n>` and nothing else. A file with no such line reports nothing, which is not the same as zero.

- **Tiers, not model names**: `haiku`, `sonnet` or `opus`. Codex maps each through `GARRICK_CODEX_MODEL_<TIER>`.
- **Name it in letters, digits, hyphens and underscores**, as in `whats-open`. Its log, heartbeat and lock files are named after it, and `agent` is taken by the lock that all assistant jobs share.
- **End the prompt with a closing line to print**, and check for it. A run that stopped early must not look like a run that found nothing.
- **Report how much it handled.** A job that runs cleanly for a week and does nothing gets flagged in its log and heartbeat, and with a notifier set, you are told.
- **Call the assistant only through `agent.py`.** A job run with `--agent` that exits 0 without adding a line for itself to the ledger gets a line in its log saying so, and `no_call` in its heartbeat. That is fine when it had nothing to ask, as the example does for a zone with nothing open. Every run, though, means it reaches the assistant some other way, where no cap or deny profile holds it: `job.py check-scripts` finds the line.
- **One zone per call** when the job reads zone material. The [walls](../principles.md) still apply to anything it writes.
- **Write outside the zones**, or into an inbox for `intake` to sort. A job decides nothing a session would have asked you about.

### Exit codes

| Code | Meaning |
|---|---|
| 3 | The answer came back without its closing line; nothing was written |
| 4 | The assistant could not sign in, twice, five minutes apart; the job did not run |
| 6 | A connector the job needs is missing |
| 8 | A spend limit was reached and nothing was called, or one call passed `GARRICK_MAX_CALL_USD` and was stopped |
| 64 | The command was wrong, or Claude's deny profile is missing, not JSON, or has lost an entry in `CORE_DENY`; nothing was called |
| 75 | The previous run still holds the lock, or another assistant job held the shared one for this run's whole time limit; this one was skipped |
| 124 | The watchdog stopped a run that went past its time limit, 25 minutes by default, or a call passed its `--timeout` |
| 127 | The job's command could not be started, or the assistant is not installed |
| 128 + N | The command was killed by signal N, or `job.py` itself was stopped by it, as a shell reports it: 143 for SIGTERM, 137 for SIGKILL |

A job may add codes of its own, such as 5 for a sweep that reached some of its sources and not all. List them in `GARRICK_QUIET_EXITS` if they are not news (see below). The words in a notice and the heartbeat's `reason` come from what `job.py` saw: "could not sign in" only when its own sign-in check failed, "timed out" only when its own watchdog stopped the run. A command that exits 4 or 124 itself reads "exited 4 after 12s".

### Being told

`job.py` tells you when a job fails, when it works again, and when it has gone idle. Where it tells you is up to you, and it can be both:

- `GARRICK_NOTIFY=1` raises a macOS notification.
- `GARRICK_NOTIFY_CMD` runs a command of yours with two more arguments, the title and the message. Its environment also holds `GARRICK_NOTIFY_KIND` (`failed`, `recovered`, `idle` or `message`), `GARRICK_JOB` and `GARRICK_EXIT`. It has a minute to finish. If it fails, a line in the job's log says so, and the run's exit code stays the job's own.

A notifier for a chat app or a mail relay is a few lines. This one appends to a file instead, which is enough to see the shape:

```sh
#!/bin/sh
# notify.sh <title> <message>
printf '%s  %s: %s (%s, exit %s)\n' "$(date '+%F %T')" "$1" "$2" "$GARRICK_JOB" "$GARRICK_EXIT" \
  >> "$HOME/Library/Logs/garrick-jobs/notices.txt"
```

In the job's plist, set `GARRICK_NOTIFY_CMD` to `/bin/sh /Users/<you>/Garrick/System/jobs/notify.sh`. Nothing leaves the machine unless your command sends it.

When a notice goes:

- **A failure** notifies on its first run, and again whenever the exit code changes. While the same failure lasts it repeats at most once an hour, or every `GARRICK_ALERT_REPEAT` seconds. The notice says why in words: could not sign in to the assistant, twice; needs a connector the assistant does not have; reached a spending cap; timed out after so many seconds; or exited with a code after so many seconds. The same words go in the log.
- **A recovery** always notifies: a job that was failing and works again says so, once.
- **An idle job**, one that has reported doing nothing for `GARRICK_IDLE_DAYS` days, notifies, and again every `GARRICK_IDLE_DAYS` days while it stays idle. Set it to 0 to turn the alarm off.
- **A quiet exit** never notifies. `GARRICK_QUIET_EXITS` lists the codes, such as `5` or `3, 5`. A quiet exit is still logged, and the heartbeat marks it `quiet`. It counts as a working run: its count feeds the idle alarm, and it ends a failure with a recovery notice.
- **A skipped run** (75) never notifies.

A job can send a line of its own, such as a morning digest, through the same notifier: `python3 System/jobs/job.py notify "Digest" "Three open, one due today."`. That line is not throttled.

### Other settings

Every setting is an environment variable, set in the job's plist under `EnvironmentVariables`. A value that is not a number keeps the default, with a line in the log saying so.

| Variable | Default | What it sets |
|---|---|---|
| `GARRICK_HARNESS` | `claude` | `claude` or `codex` |
| `GARRICK_JOB_TIMEOUT` | 1500 | seconds before the watchdog stops a run, above zero; `--timeout` sets it for one job, and a `--timeout` of zero or less is refused with exit 64 |
| `GARRICK_LOGIN_RETRY_AFTER` | 300 | seconds between the two sign-in checks |
| `GARRICK_IDLE_DAYS` | 7 | days of nothing before a job is idle, and between idle notices; 0 for no alarm |
| `GARRICK_ALERT_REPEAT` | 3600 | seconds between notices while the same failure lasts |
| `GARRICK_QUIET_EXITS` | none | exit codes that never notify, separated by commas or spaces |
| `GARRICK_NOTIFY` | off | 1 for a macOS notification |
| `GARRICK_NOTIFY_CMD` | none | a command given the title and the message |
| `GARRICK_ENV_FILE` | none | a file of `KEY=value` lines read into the run first |
| `GARRICK_JOBS_DIR` | `~/Library/Logs/garrick-jobs` | where logs, heartbeats, locks and the ledger go |
| `GARRICK_WORKSPACE` | your home folder | where the command runs when there is no `--cwd` |

`GARRICK_ENV_FILE` is for a setting you would rather not write into a plist, such as a sign-in token on a Mac nobody logs in to. Lines read as a shell reads them, `export` and quotes allowed. It is read before anything else, so it can hold any setting in the table, `GARRICK_JOBS_DIR` included; a value in the file wins over the plist's. The log names the settings it read, never their values, and warns when other users of the Mac can read the file: `chmod 600` it. On a Mac you sign in to, leave it out: Claude's own sign-in carries the claude.ai connectors, and a token does not.

### What the status page reads

Everything a job leaves is in the jobs folder, named after the job. `python3 System/jobs/job.py status` prints it all as JSON, or for the jobs you name.

| File | What it holds |
|---|---|
| `<job>.heartbeat.json` | The last run: `job`, `started`, `finished`, `finished_ts`, `exit`, `seconds`, `ok` (exit 0 or quiet), `quiet`, `reason` (the words for a failure, or empty), `items`, `idle_days`, `idle`, `agent` (whether it ran with `--agent`), `no_call` (an `--agent` run that exited 0 and added no line to the ledger), `failing_since` |
| `<job>.lock/` | Present while a run holds it. Its `until` file reads `<until> <pid> <started>`, then `<group> <group started>` once the command runs, in seconds since 1970. The lock is held while `job.py` lives, past its `until` too. Once `job.py` has gone, it is held while the command's process group still runs, until its `until`; the next fire then stops the group and takes the lock. A lock whose `job.py` and command have both gone is held by nobody |
| `<job>.alert.json` | Present while the job is failing: `exit`, `since` (the first failed run) and `alerted` (the last notice) |
| `<job>.idle-alert` | When the last idle notice went |
| `<job>.log` | One line a run, `===== <finished>  <job>  exit <code>  (<seconds>s) =====`, with `  quiet` before the closing `=====` when the exit was quiet, or `skipped` in place of the exit |
| `agent.lock/` | The lock all assistant jobs share, written the same way |

`job.py status` gives each job `running`, `lock` (its `pid`, `started` and `until`), `heartbeat`, `failing` (`exit`, `since`, `notified`), `idle_notified` and `log`, and the shared lock as `assistant_lock`.

### Limits

- The suite tests the runner, the wrapper, the caps and the example against fake assistants. The deny profile, the settings sources and the ledger's numbers were checked by hand against Claude Code 2.1.287. The permission mode was checked against Claude Code 2.1.288: a job allowed only `Read` and asked to edit a file was refused (the ledger lists `Edit` as denied) and the file was unchanged; a job allowed `WebFetch` was not given the tool, because the profile denies it. The read-only Codex command was checked against Codex 0.160.0, in a scratch folder: a shell command writing a file failed with "operation not permitted", and the run had no web search, browser, app or connector tools. The same request under the write sandbox and the user's configuration wrote the file and had all of them. Codex has not been run end to end through `job.py`.
- The sign-in check asks the assistant whether it is signed in (`claude auth status`, `codex login status`), with no model call. A scheduled job's access to the login keychain can fail now and then; the check, and its one retry five minutes later, exist for that. Only a definite no stops the job: a check that does not answer within 90 seconds, as when the Mac sleeps in the middle of it, lets the job run, with a line in the log.
- A laptop that is asleep runs nothing. launchd runs a missed calendar job when the Mac wakes, and several overdue assistant jobs then take turns rather than fail each other's sign-in. A run the lid closed on is still running when the Mac wakes, past the time on its lock: the lock stands for as long as its `job.py` lives, so the overdue fire is skipped rather than run beside it. A process number the system has since given to another process does not hold a lock: `job.py` checks when the process started (`ps -o etime=`).
- `launchctl bootout`, loading a plist again, or a shutdown sends `job.py` a SIGTERM. It stops the command's whole process group, lets go of its locks, and writes a heartbeat whose `reason` says it was stopped, with exit 143. A stop raises no notice. SIGHUP and SIGINT do the same. A signal that was already ignored when `job.py` started stays ignored, so a run started under `nohup` keeps running when the terminal or the session hook that started it ends. A hook whose end stops its whole process group, with SIGTERM, stops a run started there too, as any stop does. To start a job from a hook and let the hook end at once, pass `--detach`: `job.py` checks its arguments, starts the same run in a session of its own, and exits 0. The log and the heartbeat say how the run went. If `job.py` is killed outright (SIGKILL), its command runs on with no watchdog; the lock records the command's process group, so the next fire is skipped while it runs, and stops it once the run's time is up. If only processes the command started are left, and not the command itself, `job.py` cannot be sure the group is still that run's, so the lock stands until you stop them: the skipped run's log line names the group (`kill -TERM -<group>`).

## See them on one page

The [status page](status-page.md) reads the heartbeats, the job logs and the ledger, and shows each job's last two weeks as a strip of days next to everything else in the workspace that needs you.

## What you lose without it

Nothing about correctness. `check.py` catches exactly the same problems whether you run it once a week by hand or a launchd job runs it nightly, and every brief a job writes, you can ask for in a session. The difference is how long a problem sits before you notice it, and whether the first thing you read in the morning is already waiting.
