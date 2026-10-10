#!/usr/bin/env python3
"""Run one unattended assistant turn for a scheduled job. An optional extra.

A scheduled job never names `claude` or `codex`. It calls this, and one
environment variable picks the assistant:

    GARRICK_HARNESS=claude      the default
    GARRICK_HARNESS=codex

    python3 agent.py run --tier sonnet --allow Read --allow Grep < prompt.txt
    python3 agent.py run --tier haiku --prompt "Say hello." --timeout 600
    python3 agent.py login              exit 1 only when the assistant is not signed in
    python3 agent.py requires gmail     exit 6 when the assistant has no such connector
    python3 agent.py items 4            report how much this run did, for job.py's idle alarm
    python3 agent.py items-from out.txt report the last `ITEMS <n>` line in a file, if any
    python3 agent.py ledger             what the last 24 hours of calls did and cost

From Python: `code, text = agent.run("sonnet", prompt, allow=["Read"])`.

**Tiers, never model IDs.** `haiku`, `sonnet` and `opus` go to Claude as they
are, so a job follows each new release. Codex gets the model named in
GARRICK_CODEX_MODEL_<TIER>, or its own default when that is unset.

**What the assistant may do.** Claude takes a list of allowed tools per call
(`--allow`) and refuses any other tool that needs permission, editing and
writing files among them. On top of it, every call loads
`headless-settings.json`, beside this file, whose deny list names tools that
send, share, delete or reach the web, and a deny beats an allow. The list
may grow, but a profile that has lost any entry in CORE_DENY is refused, so
an edit that trims it cannot quietly let a job send. Its
shell rules match a command by how it starts, so they are best-effort. The
call also loads only your user and project settings, never a project's
`.claude/settings.local.json`: allow rules kept there for your own sessions
would otherwise reach a job nobody is watching.
Codex has no per-tool list and loads no profile, so the allow list picks its
sandbox. A job allowed only tools that read (READ_ONLY_TOOLS), or nothing,
runs read-only: nothing written, the user's Codex configuration ignored, and
connectors, plugins, the browser and web search switched off. Any other job
runs sandboxed to its folder, which is its write boundary, with the
connectors you have configured.

**What it spends.** Every call appends one line to `ledger.jsonl` in the jobs
folder (~/Library/Logs/garrick-jobs/ on a Mac, or GARRICK_JOBS_DIR): when,
which job, assistant, tier, model, turns, cost, seconds, exit code and any
tool the assistant was refused. The ledger keeps the last 60 days. Before a call, the
ledger is read and the call is refused, with exit 8, when the last 24 hours
already hold GARRICK_CAP_CALLS_DAY calls (48), the last hour
GARRICK_CAP_CALLS_HOUR (12), or the last 24 hours GARRICK_CAP_COST_DAY
dollars (20). Each Claude call is also stopped at GARRICK_MAX_CALL_USD
dollars (5), and then exits 8 as well. Set a cap to 0 to remove it. The cost
is Claude's own estimate at list prices, so on a subscription it measures use
rather than a bill. Codex reports neither turns nor cost, so its lines carry
none and only the call caps hold it.

**How long it may take.** With `--timeout` (or `timeout=`), a call still going
after that many seconds is stopped and exits 124, so a job can keep time for
its own steps after the call. job.py's watchdog bounds the whole run either way.

Exit codes: the assistant's own, or 6 (no connector), 8 (a cap was reached and
nothing was called, or the call passed GARRICK_MAX_CALL_USD and was stopped),
64 (usage, or Claude's deny profile is missing, not JSON, or no longer denies
everything in CORE_DENY, and nothing was called), 124 (the call passed its
--timeout), 127 (the assistant is not installed).

Standard library only, Python 3.9 or later. Not installed by install.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "headless-settings.json"
HARNESSES = ("claude", "codex")
TIERS = ("haiku", "sonnet", "opus")

EXIT_LOGIN = 4
EXIT_CONNECTOR = 6
EXIT_CAP = 8
EXIT_USAGE = 64
EXIT_TIMEOUT = 124
EXIT_MISSING = 127

DEFAULT_CAPS = {"calls_day": 48, "calls_hour": 12, "cost_day": 20.0}
DEFAULT_MAX_CALL_USD = 5.0
JOB_NAME = re.compile(r"[A-Za-z0-9_-]+")
ITEMS_LINE = re.compile(r"^ITEMS (\d+)\s*$", re.M)
MAX_LOG_BYTES = 1024 * 1024
LEDGER_DAYS = 60  # longer than every cap, a day at most, and the status page's fourteen days
# The deny entries the profile must never lose: without one of them an
# unattended run could send, share or delete. The shipped profile denies more.
CORE_DENY = (
    "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply", "mcp__claude_ai_Gmail__forward",
    "mcp__claude_ai_Gmail__trash_message", "mcp__claude_ai_Gmail__trash_thread",
    "mcp__claude_ai_Google_Calendar__create_event", "mcp__claude_ai_Google_Calendar__delete_event",
    "mcp__claude_ai_Google_Drive__share_file", "mcp__claude_ai_Google_Drive__trash_file",
    "mcp__claude_ai_Notion__notion-update-page", "mcp__claude_ai_Notion__notion-create-comment",
    "Bash(curl:*)", "Bash(git push:*)", "Bash(rm:*)",
)


# --------------------------------------------------------------------------- settings


def harness() -> str:
    return os.environ.get("GARRICK_HARNESS", "claude").strip().lower() or "claude"


def jobs_dir() -> Path:
    """Logs, heartbeats, locks and the ledger. Outside the workspace, so nothing
    here is committed, and outside the folders macOS keeps from scheduled jobs."""
    set_to = os.environ.get("GARRICK_JOBS_DIR")
    if set_to:
        return Path(set_to).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "garrick-jobs"
    return Path.home() / ".local" / "state" / "garrick-jobs"


def name_problem(name: str) -> Optional[str]:
    """Why `name` cannot name a job, or None. The name becomes the name of the
    job's files, so a `/` would put them outside the jobs folder, and the
    status page reads it from the log as one word. `agent` is the shared
    lock's."""
    if not JOB_NAME.fullmatch(name):
        return "%r is not a job name: use letters, digits, hyphens and underscores" % name
    if name.lower() == "agent":
        return "agent names the lock that every assistant job shares: choose another name"
    return None


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def caps() -> Dict[str, float]:
    return {
        "calls_day": _number("GARRICK_CAP_CALLS_DAY", DEFAULT_CAPS["calls_day"]),
        "calls_hour": _number("GARRICK_CAP_CALLS_HOUR", DEFAULT_CAPS["calls_hour"]),
        "cost_day": _number("GARRICK_CAP_COST_DAY", DEFAULT_CAPS["cost_day"]),
    }


def rotate(path: Path) -> None:
    """Past 1 MB, the file becomes `<name>.1`, replacing the one before, so a
    log never holds more than two generations."""
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass  # not there yet, or another run moved it first


# --------------------------------------------------------------------------- ledger


def ledger_path() -> Path:
    return jobs_dir() / "ledger.jsonl"


def read_ledger(path: Path, now: float, hours: float = 24) -> List[dict]:
    """The ledger lines from the last `hours`. A line that does not parse is
    skipped, never fatal: a half-written line must not stop every job."""
    if not path.exists():
        return []
    since = now - hours * 3600
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("ts"), (int, float)) and entry["ts"] >= since:
            out.append(entry)
    return out


def cap_reason(entries: Iterable[dict], now: float, limits: Dict[str, float]) -> Optional[str]:
    """Why the next call must not run, or None. Refused calls cost nothing and
    are not counted, so a refusal never extends its own window."""
    calls = [e for e in entries if not e.get("refused")]
    day = [e for e in calls if now - e["ts"] < 86400]
    hour = [e for e in calls if now - e["ts"] < 3600]
    if limits["calls_day"] and len(day) >= limits["calls_day"]:
        return "%d calls in the last 24 hours, the cap is %g" % (len(day), limits["calls_day"])
    if limits["calls_hour"] and len(hour) >= limits["calls_hour"]:
        return "%d calls in the last hour, the cap is %g" % (len(hour), limits["calls_hour"])
    spent = sum(float(e.get("cost_usd") or 0) for e in day)
    if limits["cost_day"] and spent >= limits["cost_day"]:
        return "$%.2f spent in the last 24 hours, the cap is $%g" % (spent, limits["cost_day"])
    return None


def append_ledger(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    prune_ledger(path, time.time())


def prune_ledger(path: Path, now: float, days: float = LEDGER_DAYS) -> None:
    """Keep the ledger to its last `days` days: it is read whole before every
    call. It is rewritten only once its first line is a day past that, so at
    most about once a day, and a failure leaves it as it was."""
    try:
        with path.open("rb") as f:
            first = f.readline()
    except OSError:
        return
    try:
        ts = json.loads(first.decode("utf-8", "replace")).get("ts")
    except (ValueError, AttributeError):
        ts = None
    if isinstance(ts, (int, float)) and ts >= now - (days + 1) * 86400:
        return
    keep = read_ledger(path, now, days * 24)
    tmp = path.with_name(".%s.%d.tmp" % (path.name, os.getpid()))
    try:
        tmp.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in keep), encoding="utf-8")
        tmp.replace(path)  # a reader sees the old file or the new one, never half of either
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def ledger_entry(now: float, job: str, tier: str, outcome: dict, seconds: float, code: int,
                 refused: str = "") -> dict:
    entry = {
        "ts": round(now, 3),
        "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "job": job,
        "harness": harness(),
        "tier": tier,
        "turns": outcome.get("turns"),
        "cost_usd": outcome.get("cost_usd"),
        "seconds": round(seconds, 1),
        "exit": code,
        "denied": outcome.get("denied", []),
        "subtype": outcome.get("subtype"),
        "model": outcome.get("model"),
    }
    if refused:
        entry["refused"] = refused
    return entry


# --------------------------------------------------------------------------- one call


def parse_claude_output(stdout: str) -> dict:
    """The answer and the numbers from `claude -p --output-format json`. When the
    output is not that JSON (an error printed before any turn ran), the raw text
    is the answer and the numbers are unknown, never zero."""
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and ("result" in data or data.get("type") == "result"):
            denied = {d.get("tool_name") for d in data.get("permission_denials") or [] if isinstance(d, dict)}
            usage = data.get("modelUsage")
            return {
                "text": data.get("result") or "",
                "turns": data.get("num_turns"),
                "cost_usd": data.get("total_cost_usd"),
                "denied": sorted(d for d in denied if d),
                "subtype": data.get("subtype"),
                # The models the call used, which the tier alone does not say.
                "model": ("+".join(sorted(usage)) or None) if isinstance(usage, dict) else None,
                "is_error": bool(data.get("is_error")),
                "parsed": True,
            }
    return {"text": stdout, "turns": None, "cost_usd": None, "denied": [], "subtype": None,
            "model": None, "is_error": False, "parsed": False}


def profile_problem(path: Path) -> Optional[str]:
    """Why the deny profile cannot be used, or None. Given a settings file that
    is not there, Claude carries on without its deny list, and given one that
    has lost an entry, without that entry, so the runner checks first."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "is missing"
    except (OSError, ValueError):
        return "is not readable JSON"
    permissions = data.get("permissions") if isinstance(data, dict) else None
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    if not isinstance(deny, list):
        return "has no deny list (permissions.deny)"
    missing = [t for t in CORE_DENY if t not in deny]
    if missing:
        return "no longer denies %s" % ", ".join(missing)
    return None


def claude_command(tier: str, prompt: str, allow: List[str], budget: float, profile: Path = PROFILE) -> List[str]:
    # The default mode: with nobody to ask, Claude refuses every tool that
    # needs permission unless the allow list, or an allow rule in the user's
    # own settings, names it. The mode is named rather than left out, so a
    # defaultMode in those settings, such as acceptEdits, cannot change it.
    cmd = ["claude", "-p", prompt, "--model", tier,
           "--permission-mode", "default",
           "--settings", str(profile),
           "--setting-sources", "user,project",
           "--output-format", "json"]
    if budget > 0:
        cmd += ["--max-budget-usd", "%g" % budget]
    if allow:
        cmd += ["--allowedTools"] + list(allow)  # last: the flag takes every word after it
    return cmd


# Tools that only read. A job allowed nothing else runs under Codex read-only.
READ_ONLY_TOOLS = ("Read", "Grep", "Glob", "LS")
# What a read-only Codex run switches off besides the sandbox: the connectors
# (ChatGPT apps) and plugins, which the sandbox does not govern and which can
# send, and the browser, computer use and image generation.
CODEX_READ_ONLY_OFF = ("apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
                       "computer_use", "image_generation")


def read_only(allow: Iterable[str]) -> bool:
    """Whether a job allowed these tools only reads: Claude's allow list, read
    for Codex, which has no list of its own."""
    return all(tool in READ_ONLY_TOOLS for tool in allow)


def codex_command(tier: str, prompt: str, last_message: Path, allow: Iterable[str] = ()) -> List[str]:
    # A job that only reads gets a sandbox that writes nothing, none of the
    # user's own configuration (MCP servers, plugins, hooks, notify programs),
    # no connectors, no web search, and no session file left behind. Any
    # other job gets a sandbox that writes inside its folder, with the user's
    # configuration, connectors included: a mail job needs its mail.
    model = os.environ.get("GARRICK_CODEX_MODEL_%s" % tier.upper(), "").strip()
    cmd = ["codex", "exec"]
    if model:
        cmd += ["-m", model]
    if read_only(allow):
        cmd += ["--sandbox", "read-only", "--ignore-user-config", "--ephemeral", "-c", 'web_search="disabled"']
        for feature in CODEX_READ_ONLY_OFF:
            cmd += ["--disable", feature]
    else:
        cmd += ["--sandbox", "workspace-write"]
    cmd += ["-c", 'approval_policy="never"', "--skip-git-repo-check", "-o", str(last_message), prompt]
    return cmd


def call(cmd: List[str], cwd: Optional[Path], timeout: Optional[float], stdout=subprocess.PIPE) -> Tuple[int, str, str]:
    """Run the assistant's command: its exit code, stdout and stderr. Past
    `timeout` seconds it is asked to stop, then made to, and the code is 124.
    The assistant stays in the job's process group, so job.py's watchdog
    still reaches it."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=stdout,
                            stderr=subprocess.PIPE if stdout is subprocess.PIPE else subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True)
    try:
        out, err = proc.communicate(timeout=timeout if timeout and timeout > 0 else None)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return EXIT_TIMEOUT, out or "", err or ""


def run(tier: str, prompt: str, allow: Iterable[str] = (), cwd: Optional[Path] = None,
        job: Optional[str] = None, timeout: Optional[float] = None) -> Tuple[int, str]:
    """One headless turn. Returns the exit code and the assistant's final answer.
    With `timeout`, a call still going after that many seconds is stopped and
    returns 124 with whatever answer it had."""
    allow = list(allow)
    h = harness()
    if h not in HARNESSES:
        print("agent: GARRICK_HARNESS is %r; use claude or codex" % h, file=sys.stderr)
        return EXIT_USAGE, ""
    if tier not in TIERS:
        print("agent: tier %r; use %s" % (tier, ", ".join(TIERS)), file=sys.stderr)
        return EXIT_USAGE, ""
    profile = PROFILE
    problem = profile_problem(profile) if h == "claude" else None
    if problem:
        print("agent: the deny profile %s %s, so nothing was called. Copy headless-settings.json "
              "from Garrick's extras/jobs/ beside agent.py, or put those entries back." % (profile, problem),
              file=sys.stderr)
        return EXIT_USAGE, ""
    job = job or os.environ.get("GARRICK_JOB") or "manual"
    problem = name_problem(job)
    if problem:
        print("agent: %s" % problem, file=sys.stderr)
        return EXIT_USAGE, ""
    ledger = ledger_path()
    now = time.time()
    reason = cap_reason(read_ledger(ledger, now), now, caps())
    if reason:
        print("agent: not run, %s. Raise GARRICK_CAP_* or wait." % reason, file=sys.stderr)
        append_ledger(ledger, ledger_entry(now, job, tier, {}, 0, EXIT_CAP, refused=reason))
        return EXIT_CAP, ""

    start = time.time()
    if h == "claude":
        cmd = claude_command(tier, prompt, list(allow), _number("GARRICK_MAX_CALL_USD", DEFAULT_MAX_CALL_USD),
                             profile)
        try:
            code, out, err = call(cmd, cwd, timeout)
        except FileNotFoundError:
            print("agent: claude is not installed, or not on PATH", file=sys.stderr)
            return EXIT_MISSING, ""
        if err:
            sys.stderr.write(err)
        outcome = parse_claude_output(out)
        code = code or (1 if outcome["is_error"] else 0)
        if outcome["subtype"] == "error_max_budget_usd":
            # Stopped by its own budget: a cap, like a refusal, not a fault in the job.
            print("agent: the call passed its budget of $%g (GARRICK_MAX_CALL_USD) and was stopped"
                  % _number("GARRICK_MAX_CALL_USD", DEFAULT_MAX_CALL_USD), file=sys.stderr)
            code = EXIT_CAP
        if code == EXIT_TIMEOUT and timeout:
            print("agent: the call was stopped after %gs (--timeout)" % timeout, file=sys.stderr)
    else:
        # Codex prints the whole run, prompt included. A job greps its answer for
        # sentinel lines the prompt also contains, so it gets the final message
        # alone and the transcript goes to a file beside the log. It holds what
        # the run read, zone material included, so it is rotated like the log.
        transcript = Path(os.environ.get("GARRICK_TRANSCRIPT") or jobs_dir() / ("%s.transcript.log" % job))
        transcript.parent.mkdir(parents=True, exist_ok=True)
        rotate(transcript)
        with tempfile.TemporaryDirectory() as tmp:
            last = Path(tmp) / "last.txt"
            try:
                with transcript.open("a", encoding="utf-8") as log:
                    code, _, _ = call(codex_command(tier, prompt, last, allow), cwd, timeout, stdout=log)
            except FileNotFoundError:
                print("agent: codex is not installed, or not on PATH", file=sys.stderr)
                return EXIT_MISSING, ""
            text = last.read_text(encoding="utf-8", errors="replace") if last.exists() else ""
        outcome = {"text": text, "turns": None, "cost_usd": None, "denied": [], "subtype": None}
        if code == EXIT_TIMEOUT and timeout:
            print("agent: the call was stopped after %gs (--timeout)" % timeout, file=sys.stderr)
    append_ledger(ledger, ledger_entry(start, job, tier, outcome, time.time() - start, code))
    return code, outcome["text"]


# --------------------------------------------------------------------------- before a run


def login_ok(cwd: Optional[Path] = None) -> bool:
    """Whether the assistant can sign in from this run, without a model call.
    Only a definite no is False: a check that did not answer in time is not
    evidence of a lost sign-in."""
    return login_state(cwd) is not False


def login_state(cwd: Optional[Path] = None) -> Optional[bool]:
    """True when signed in, False when the assistant says it is not or is not
    installed, None when the check did not answer within 90 seconds. A Mac
    that sleeps during the check runs out its time on waking, and treating
    that as a lost sign-in would stop every assistant job that morning.
    Run from the workspace, never from `/`, where a scheduled job starts: an
    assistant started there can reach into ~/Desktop and set off a macOS
    permission prompt that nobody is there to answer."""
    cwd = cwd or Path.cwd()
    if harness() == "claude":
        cmd = ["claude", "auth", "status", "--json"]
    else:
        cmd = ["codex", "login", "status"]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=90,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return None
    out = (proc.stdout + proc.stderr).strip()
    if harness() == "claude":
        try:
            return bool(json.loads(proc.stdout).get("loggedIn"))
        except (ValueError, AttributeError):
            return proc.returncode == 0 and "not logged in" not in out.lower()
    low = out.lower()
    return "logged in" in low and "not logged in" not in low


def connectors_available(names: Iterable[str], listing: str) -> List[str]:
    """The names in `names` that no connected server in `listing` matches."""
    connected = []
    for line in listing.splitlines():
        low = line.lower()
        if not low.strip() or any(w in low for w in ("disabled", "failed", "needs auth", "checking")):
            continue
        # Claude prints "name: command - status"; Codex prints a table, name first.
        server = low.split(":", 1)[0].strip() if ":" in low else low.split()[0]
        if server != "name":
            connected.append(server)
    return [n for n in names if not any(n.lower() in s for s in connected)]


def requires(names: Iterable[str], cwd: Optional[Path] = None) -> int:
    """0 when every connector named is there, 6 when one is missing. A job that
    ran without its mail connector would report nothing found, every night,
    for a reason its log would never name."""
    names = [n for n in names if n]
    if not names:
        return 0
    cmd = ["claude", "mcp", "list"] if harness() == "claude" else ["codex", "mcp", "list"]
    try:
        listing = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120,
                                 stdin=subprocess.DEVNULL).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        listing = ""
    missing = connectors_available(names, listing)
    if missing:
        print("agent: %s has no connector for %s. Job not started." % (harness(), ", ".join(missing)),
              file=sys.stderr)
        return EXIT_CONNECTOR
    return 0


def report_items(n: int) -> None:
    """How much real work this run did, for the idle alarm in job.py. Report
    nothing when unsure: a run that forgot to count is not a run that found
    nothing."""
    target = os.environ.get("GARRICK_ITEMS_FILE")
    if target:
        Path(target).write_text("%d\n" % n, encoding="utf-8")


def items_from(text: str) -> Optional[int]:
    """The number on the last `ITEMS <n>` line in an answer, or None. A prompt
    asks the assistant to end with that line when the job's count is the
    assistant's to make."""
    found = ITEMS_LINE.findall(text or "")
    return int(found[-1]) if found else None


def report_items_from(text: str) -> Optional[int]:
    """Report the count in an answer's `ITEMS <n>` line. No line, no report:
    not zero."""
    n = items_from(text)
    if n is not None:
        report_items(n)
    return n


# --------------------------------------------------------------------------- command line


def summary(entries: List[dict]) -> str:
    calls = [e for e in entries if not e.get("refused")]
    refused = len(entries) - len(calls)
    cost = sum(float(e.get("cost_usd") or 0) for e in calls)
    lines = ["%d call%s, $%.2f, %d refused by a cap" % (len(calls), "" if len(calls) == 1 else "s", cost, refused)]
    by_job: Dict[str, List[dict]] = {}
    for e in calls:
        by_job.setdefault(e.get("job", "?"), []).append(e)
    for job, rows in sorted(by_job.items()):
        spent = sum(float(e.get("cost_usd") or 0) for e in rows)
        failed = sum(1 for e in rows if e.get("exit"))
        denied = sorted({t for e in rows for t in e.get("denied") or []})
        line = "  %s: %d call%s, $%.2f" % (job, len(rows), "" if len(rows) == 1 else "s", spent)
        if failed:
            line += ", %d failed" % failed
        if denied:
            line += ", refused tools: %s" % ", ".join(denied)
        lines.append(line)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="One unattended assistant turn, for a scheduled job.")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="run one turn; the prompt comes from --prompt, --prompt-file or stdin")
    r.add_argument("--tier", required=True, choices=TIERS)
    r.add_argument("--allow", action="append", default=[], help="a tool the assistant may use (Claude only)")
    given = r.add_mutually_exclusive_group()
    given.add_argument("--prompt", help="the prompt itself")
    given.add_argument("--prompt-file")
    r.add_argument("--cwd")
    r.add_argument("--timeout", type=float, help="seconds before the call is stopped, with exit 124")
    sub.add_parser("login", help="exit 1 when the assistant is not signed in")
    q = sub.add_parser("requires", help="exit 6 when a connector is missing")
    q.add_argument("names", nargs="+")
    i = sub.add_parser("items", help="report how much this run did, for the idle alarm")
    i.add_argument("count", type=int)
    f = sub.add_parser("items-from", help="report the last ITEMS <n> line of a file (- for stdin)")
    f.add_argument("file")
    l = sub.add_parser("ledger", help="what recent calls did and cost")
    l.add_argument("--hours", type=float, default=24)
    args = ap.parse_args(argv)

    if args.command == "run":
        if args.prompt is not None:
            prompt = args.prompt
        elif args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        else:
            prompt = sys.stdin.read()
        if not prompt.strip():
            print("agent: empty prompt", file=sys.stderr)
            return EXIT_USAGE
        code, text = run(args.tier, prompt, args.allow, Path(args.cwd) if args.cwd else None,
                         timeout=args.timeout)
        if text:
            print(text if text.endswith("\n") else text + "\n", end="")
        return code
    if args.command == "login":
        state = login_state()
        if state is None:
            print("agent: %s did not answer the sign-in check in time" % harness(), file=sys.stderr)
        return 1 if state is False else 0
    if args.command == "requires":
        return requires(args.names)
    if args.command == "items":
        if args.count < 0:
            print("agent: a count is zero or more", file=sys.stderr)
            return EXIT_USAGE
        report_items(args.count)
        return 0
    if args.command == "items-from":
        source = sys.stdin if args.file == "-" else None
        try:
            text = source.read() if source else Path(args.file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print("agent: %s" % exc, file=sys.stderr)
            return 0  # no count is no report, never a failed job
        report_items_from(text)
        return 0
    print(summary(read_ledger(ledger_path(), time.time(), args.hours)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
