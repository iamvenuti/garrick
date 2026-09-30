# Extra: scheduled jobs

`System/tools/check.py` is a script you run. Nothing in Garrick schedules it, or anything else, to run on its own; there's no cron entry, no launchd job, no background process installed by `install.py`. Running the check, wrapping a thread, filing a meeting: all of it happens because you or your assistant did it in a session, not because something was waiting to fire.

## How to add one

On macOS, a launchd agent is the usual way to run something on a schedule without a terminal open. A plist that runs `/usr/bin/python3 /Users/<you>/Garrick/System/tools/check.py --json` once a day, writing its output somewhere you'll see it, is the smallest version. launchd does not expand `~` or start in your workspace, so every path in the plist has to be spelled out in full. This is also why the installer refuses a workspace under `~/Documents`, `~/Desktop`, `~/Downloads` or `~/Library`: macOS stops a scheduled job from reading there. The job fixes nothing on its own; it tells you sooner that something needs fixing. The same mechanism runs the optional mail fetcher, `extras/fetch/imap_fetch.py --config <file>`, every few minutes (see [ways in](ways-in.md)), and could run a git status sweep across every zone, or a reminder to look at `Todo.md`, if you build it. A fetcher run on a schedule only saves mail into a zone's inbox; sorting it still waits for you to say "process the inbox".

## What it would add

Problems surfacing on a schedule instead of only when you happen to run the check yourself: a wall naming a tag that is not in the Parties table, a deliverable that slipped through without its date prefix, a meeting page still missing its zone or parties. The same applies to any other automation you might want, a nightly reminder of open actions, a weekly digest, none of which Garrick ships but all of which can run against the same files the same way a manual run does.

## What you lose without it

Nothing about correctness. `check.py` catches exactly the same problems whether you run it once a week by hand or a launchd job runs it nightly; the only difference is how long a problem sits before you notice it.
