#!/usr/bin/env python3
"""The acceptance run: the path a user takes in a day, on a release candidate (#513).

    python3 tests/acceptance/run.py [--candidate ZIP | --commit REF] [--model stub|claude]
                                    [--report FILE] [--compare TAG] [--previous TAG]
                                    [--steps a,b,c] [--keep]

The candidate is a release zip (git archive --format=zip --prefix=garrick/) or a
commit of this clone, which is archived the same way. Everything runs in one
temporary folder: the unpacked candidate, the workspaces, a home folder and a
jobs folder of its own. HOME, GARRICK_HOME and GARRICK_JOBS_DIR point into it, so
nothing of this Mac's workspace, jobs or assistant sessions is read or written.

The steps, in order. A step that needs what an earlier step made is skipped,
and says so, when that one failed:

    install   install from the zip; the check is clean
    demo      build the demo; its finished page shows the demo's work and no job of this machine
    file      file one conversation from its inbox
    brief     ask for a brief; the wall holds the other side back
    wrap      wrap a thread
    restart   start the page builder again, in a new process
    resume    the Resume here block and the Next action are what the wrap wrote
    correct   "that's wrong, it's Y": every live copy changes, the record does not
    update    install the previous tag, update it to the candidate
    names     a workspace of v0.76.0 with a grown context.md, updated and then given the yes (--names): People and
              Aliases are in System/names.md, every row kept once, context.md under 8,000 characters (#653). The
              tables have a Learned column that the older rows do not fill, so those rows are one cell short:
              each is padded in names.md to the header's cells (#663)
    hooks     a workspace whose assistants name the zone guard through $HOME, in a kept download of the previous release:
              the update report names the guard as another version's and offers to refresh the kept hooks; with stdin
              closed and no flag nothing is copied and the flag is named, and with --refresh-hooks and stdin closed
              the folder holds this release's hook files and the settings are unchanged (#670, #672, #680)
    refused   a save the wall check refuses is not shown as saved
    ask       the fixed Ask set (ask_set.json) on the demo workspace

--model stub (the default, and what CI runs) does a step that needs a model with
a stand-in that calls the same tools and checks the same outcome, and says in the
report which part of the step no model wrote. --model claude runs those steps with
`claude -p`, headless, in the temporary workspace; the assistant's own state goes to
a folder in the temporary home, and only its sign-in variables are passed on.

Each step records pass, fail or skipped, and why. A failed step makes the run exit
1. A skipped step is printed, never hidden. --report writes the Markdown report.
--compare TAG runs the Ask set on that tag as well, and shows both side by side.
Standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASK_SET = HERE / "ask_set.json"

STEPS = ("install", "demo", "file", "brief", "wrap", "restart", "resume", "correct", "update", "names", "hooks", "refused", "ask")
# The demo's thread this run wraps, the call it files, and the fact it corrects.
ZONE, PROJECT, THREAD = "Birch", "Birch Entry", "Launch Plan"
SIDE_ACME, SIDE_BIRCH = "261027-cobalt-renewal-for-acme", "261103-cobalt-northern-lane-for-birch"
_SIDE_ACME, _SIDE_BIRCH = SIDE_ACME, SIDE_BIRCH
# The demo moves its month forward by whole weeks so that its last day is the build day or one of the six before
# (examples/demo/build.py, `weeks_for`). The names above and the dates in ask_set.json are as a build in the week of
# 9 to 15 November 2026 writes them; `moved()` takes them to the week the run builds in.
DEMO_LAST_DAY, FIXTURE_LAST_DAY = datetime.date(2026, 9, 28), datetime.date(2026, 11, 9)
FIXTURE_DATE = re.compile(r"(?<!\d)(2[6-9][01]\d[0-3]\d)(?!\d)")


def fixture_shift(today):
    """How far the fixtures' dates move for a demo built on `today`: whole weeks, zero in their own week."""
    weeks = (today - DEMO_LAST_DAY).days // 7
    return DEMO_LAST_DAY + datetime.timedelta(days=7 * weeks) - FIXTURE_LAST_DAY


def moved(value, shift):
    """`value` (a string, or lists and dicts of them) with every YYMMDD date moved by `shift`."""
    if isinstance(value, str):
        if not shift:
            return value
        def one(m):
            day = datetime.datetime.strptime(m.group(1), "%y%m%d").date() + shift
            return day.strftime("%y%m%d")
        return FIXTURE_DATE.sub(one, value)
    if isinstance(value, list):
        return [moved(v, shift) for v in value]
    if isinstance(value, dict):
        return {k: moved(v, shift) for k, v in value.items()}
    return value
OLD_FACT, NEW_FACT = "twelve hundred pallets", "fourteen hundred pallets"
NEXT_ACTION = "Send Ruth the distributor questions before her first call; Sam's."
HOST_JOB = "zz-host-nightly"
WALL_SAID = "A wall holds some material back from this project"
CLAUDE_KEEP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL")


class Fail(Exception):
    """The step did not hold. The message says what, in a line."""


class Skip(Exception):
    """The step could not run, and says why."""


class Step:
    def __init__(self, key, title):
        self.key, self.title = key, title
        self.status, self.why, self.notes, self.seconds = "skipped", "not run", [], 0.0

    def note(self, text):
        self.notes.append(text)


def sh(cmd, cwd=None, env=None, timeout=900, check=True, stdin=None):
    r = subprocess.run([str(c) for c in cmd], cwd=None if cwd is None else str(cwd), env=env, input=stdin,
                       capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise Fail("%s exited %d: %s" % (" ".join(str(c) for c in cmd[:3]), r.returncode, " | ".join(tail)))
    return r


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Run:
    def __init__(self, args):
        self.args = args
        self.model = args.model
        self.tmp = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="garrick-acceptance-")).resolve()
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.home, self.jobs = self.tmp / "home", self.tmp / "jobs"
        self.home.mkdir(exist_ok=True)
        self.jobs.mkdir(exist_ok=True)
        self.today = datetime.date.today()
        global SIDE_ACME, SIDE_BIRCH
        self.shift = fixture_shift(self.today)
        SIDE_ACME, SIDE_BIRCH = moved(_SIDE_ACME, self.shift), moved(_SIDE_BIRCH, self.shift)
        self.env = self.make_env()
        self.cand = None            # the unpacked candidate: the folder that holds install.py
        self.commit = ""
        self.demo = self.tmp / "demo"
        self.state = {}             # what a step leaves for the next
        self.failed = set()
        self.steps = []
        self.ask_rows = []

    # -- the environment: nothing of this Mac's workspace, jobs or sessions

    def make_env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CMUX_", "GARRICK_")) and not k.startswith("CLAUDE")
               and k not in CLAUDE_KEEP and k not in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME")}
        env.update({"HOME": str(self.home), "GARRICK_HOME": str(self.home), "GARRICK_JOBS_DIR": str(self.jobs),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "GIT_AUTHOR_NAME": "Acceptance", "GIT_AUTHOR_EMAIL": "acceptance@localhost",
                    "GIT_COMMITTER_NAME": "Acceptance", "GIT_COMMITTER_EMAIL": "acceptance@localhost"})
        return env

    def claude_env(self):
        env = dict(self.env)
        for k in CLAUDE_KEEP:
            if k in os.environ:
                env[k] = os.environ[k]
        env["CLAUDE_CONFIG_DIR"] = str(self.home / "claude")
        return env

    # -- the candidate

    def prepare(self):
        zpath = None
        if self.args.candidate:
            zpath = Path(self.args.candidate).resolve()
            self.commit = "zip %s" % zpath.name
        else:
            ref = self.args.commit or "HEAD"
            self.commit = sh(["git", "rev-parse", "--short", ref], cwd=REPO).stdout.strip()
            zpath = self.tmp / "candidate.zip"
            sh(["git", "archive", "--format=zip", "--prefix=garrick/", "-o", zpath, ref], cwd=REPO)
        self.cand = self.unpack(zpath, self.tmp / "candidate")

    def unpack(self, zpath, into):
        into.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(into)
        inside = [p for p in into.iterdir() if p.is_dir()]
        if len(inside) != 1 or not (inside[0] / "install.py").is_file():
            raise Fail("%s does not unpack into one folder that holds install.py" % zpath)
        return inside[0]

    def tag_tree(self, tag, name):
        zpath = self.tmp / ("%s.zip" % name)
        r = sh(["git", "archive", "--format=zip", "--prefix=garrick/", "-o", zpath, tag], cwd=REPO, check=False)
        if r.returncode != 0:
            raise Skip("tag %s is not in this clone (fetch the tags)" % tag)
        return self.unpack(zpath, self.tmp / name)

    def previous_tag(self):
        if self.args.previous:
            return self.args.previous
        r = sh(["git", "tag", "--list", "v[0-9]*", "--sort=-version:refname"], cwd=REPO, check=False)
        tags = r.stdout.split()
        if not tags:
            raise Skip("this clone has no release tag to update from (fetch the tags)")
        # The newest release tag that is an ancestor of the candidate and does not point at it.
        mine = self.candidate_commit()
        for t in tags:
            at = sh(["git", "rev-parse", "%s^{commit}" % t], cwd=REPO, check=False).stdout.strip()
            if not at or (mine and at == mine):
                continue
            if mine and sh(["git", "merge-base", "--is-ancestor", at, mine], cwd=REPO, check=False).returncode != 0:
                continue
            return t
        raise Fail("no release tag is an ancestor of the candidate other than its own commit")

    def candidate_commit(self):
        """The candidate's full commit, from the commit given or the `commit:` line a release zip carries; "" when unknown."""
        if self.args.candidate:
            m = re.search(r"(?m)^commit: *([0-9a-f]{7,40})\s*$", (self.cand / "VERSION").read_text(encoding="utf-8")) \
                if (self.cand / "VERSION").is_file() else None
            short = m.group(1) if m else ""
        else:
            short = self.args.commit or "HEAD"
        if not short:
            return ""
        return sh(["git", "rev-parse", "%s^{commit}" % short], cwd=REPO, check=False).stdout.strip()

    # -- helpers on a workspace

    def check(self, root, cand=None):
        tool = Path(root) / "System" / "tools" / "check.py"
        r = sh([sys.executable, tool, "--root", root, "--json"], env=self.env, check=False)
        try:
            report = json.loads(r.stdout)
        except ValueError:
            raise Fail("check.py printed no report: %s" % (r.stderr.strip() or r.stdout.strip())[:200])
        if report.get("errors") or report.get("warnings"):
            first = (report.get("findings") or [{}])[0]
            raise Fail("check.py found %s error(s) and %s warning(s); first: %s" % (
                report.get("errors"), report.get("warnings"), str(first.get("message", first))[:200]))

    def git(self, root, repo, *args, check=True):
        return sh(["git", "-C", Path(root) / repo, *args], env=self.env, check=check)

    def commit_in(self, root, repo, message):
        self.git(root, repo, "add", "-A")
        r = self.git(root, repo, "commit", "-q", "-m", message, check=False)
        if r.returncode != 0:
            raise Fail("the commit in %s was refused: %s" % (repo, (r.stderr or r.stdout).strip()[:200]))

    def page(self, root):
        return (Path(root) / "System" / "generated" / "status.html").read_text(encoding="utf-8")

    def build_page(self, root):
        sh([sys.executable, Path(root) / "System" / "status" / "status.py", "--workspace", root], env=self.env, cwd=root)

    def thread_note(self, root):
        return Path(root) / "Zones" / ZONE / PROJECT / "Threads" / THREAD / (THREAD + ".md")

    def model_run(self, prompt, cwd, timeout=900):
        if not shutil_which("claude"):
            raise Fail("--model claude needs the claude command on PATH")
        (self.home / "claude").mkdir(exist_ok=True)
        r = sh(["claude", "-p", prompt], cwd=cwd, env=self.claude_env(), timeout=timeout, check=False)
        if r.returncode != 0:
            raise Fail("claude -p exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200]))
        return r.stdout

    # -- the steps

    def step_install(self, s):
        target = self.tmp / "installed"
        sh([sys.executable, self.cand / "install.py", "--config", self.cand / "examples" / "acme.json", "--target", target],
           env=self.env, cwd=self.cand, timeout=900)
        for rel in ("AGENTS.md", "System/rules.md", "System/garrick-version.json"):
            if not (target / rel).is_file():
                raise Fail("the install left no %s" % rel)
        self.check(target)
        s.note("installed from %s; check.py is clean" % self.commit)

    def step_demo(self, s):
        # A job of this machine, failing, in the jobs folder the build is given: the finished page must not show it.
        beat = {"agent": False, "exit": 1, "failing_since": "2026-11-01 03:00:00", "finished": "2026-11-10 03:00:00",
                "finished_ts": 1794276000.0, "idle": False, "idle_days": 0, "items": 0, "job": HOST_JOB, "no_call": False,
                "ok": False, "quiet": False, "reason": "host job failed", "seconds": 5, "started": "2026-11-10 02:59:55"}
        (self.jobs / (HOST_JOB + ".heartbeat.json")).write_text(json.dumps(beat), encoding="utf-8")
        sh([sys.executable, self.cand / "examples" / "demo" / "build.py", "--target", self.demo, "--today", self.today.isoformat()],
           env=self.env, cwd=self.cand, timeout=1200)
        self.check(self.demo)
        if not (self.demo / "System" / "generated" / "status.html").is_file():
            raise Fail("the demo has no finished status page (it was not built after the replay)")
        page = self.page(self.demo)
        for name in ("Supplier Map", "Freight Terms", "Carrier Choice", "Launch Plan", "Kitchen", "Roof Repair"):
            if name not in page:
                raise Fail("the demo's finished page does not show the thread %s (the page was not rebuilt after the replay)" % name)
        if HOST_JOB in page:
            raise Fail("the demo's page shows a job of the machine it was built on")
        inbox = self.demo / "Wikis" / "Meetings" / "raw" / "inbox"
        if len([p for p in inbox.iterdir() if not p.name.startswith(".")]) != 1:
            raise Fail("the demo's Meetings inbox does not hold exactly one transcript")
        s.note("demo built, check.py clean; its page shows the live threads and no host job")

    def step_file(self, s):
        root = self.demo
        inbox = root / "Wikis" / "Meetings" / "raw" / "inbox"
        (waiting,) = [p for p in inbox.iterdir() if not p.name.startswith(".")]
        date = re.search(r"\d{4}-\d{2}-\d{2}", waiting.name).group(0)
        slug = "%s-theo-marsh-call" % date[2:].replace("-", "")
        if self.model == "claude":
            self.model_run("Process the inbox: file the transcript waiting in the Meetings inbox, in the Birch zone.", root)
            pages = list((root / "Wikis" / "Meetings" / "wiki" / "sources").glob("%s-*.md" % date[2:].replace("-", "")))
            if not pages:
                raise Fail("no Meetings page for the %s call exists after the model's filing" % date)
        else:
            ing = root / "System" / "skills" / "meetings" / "ingest.py"
            sh([sys.executable, ing, "--root", root, "--today", date, "land", "--inbox", waiting, "--date", date,
                "--title", "Theo Marsh call"], env=self.env, cwd=root)
            page = root / "Wikis" / "Meetings" / "wiki" / "sources" / (slug + ".md")
            page.write_text(
                "---\ntitle: Theo Marsh call\ntype: meeting\ndate: %s\nzone: Birch\nparties: [birch]\n"
                "people: [\"[[wiki/people/theo-marsh]]\"]\nraw: \"[[raw/%s]]\"\ncreated: %s\nupdated: %s\n---\n\n"
                "# Theo Marsh call\n\nCall of %s with Theo Marsh, filed by the acceptance run.\n" % (date, slug, date, date, date),
                encoding="utf-8")
            sh([sys.executable, ing, "--root", root, "--today", date, "log", "--slug", slug, "--title", "Theo Marsh call",
                "--zone", ZONE, "--parties", "birch"], env=self.env, cwd=root)
            sh([sys.executable, ing, "--root", root, "--today", date, "index"], env=self.env, cwd=root)
            self.commit_in(root, "Wikis", "Meetings: ingest %s, Theo Marsh call" % slug)
            s.note("the page was written by a stand-in: no model summarised the call (skipped (stub))")
        if any(p for p in inbox.iterdir() if not p.name.startswith(".")):
            raise Fail("the transcript is still in the Meetings inbox")
        if not list((root / "Wikis" / "Meetings" / "raw").glob("%s-*" % date[2:].replace("-", ""))):
            raise Fail("the transcript is not in raw/")
        self.check(root)
        s.note("the transcript left the inbox for raw/, a page names its zone, check.py is clean")

    def step_brief(self, s):
        if self.model == "claude":
            out = self.model_run("Prep me for Cobalt", root_zone(self.demo, ZONE))
            if "nine percent" in out.lower() or "twelve hundred" in out.lower() or "fourteen hundred" in out.lower():
                raise Fail("the brief for the Birch window carries the other side's call")
            s.note("the brief holds nothing of the other side's call")
            return
        row = self.ask_one(self.demo, {"id": "brief", "window": ZONE, "q": "Prep me for Cobalt",
                                       "find": {"route": "meetings", "words": ["cobalt"]}})
        paths = " ".join(row["paths"])
        if SIDE_BIRCH not in paths:
            raise Fail("the brief's records do not hold the Birch-side call")
        if SIDE_ACME in paths:
            raise Fail("the brief's records hold the Acme-side call across the wall")
        s.note("the records for the brief hold the Birch-side call and not the Acme-side call, which sits in another walled zone")
        s.note("the brief itself was not written: no model ran (skipped (stub))")

    def seed_old_entries(self, root, note):
        """Seven dated entries from long ago, committed, so that a wrap has something to move to history."""
        text = note.read_text(encoding="utf-8")
        old = "".join("\n**%d January 2025.** An old entry from the acceptance run, number %d.\n" % (d, d) for d in range(2, 9))
        note.write_text(text.rstrip("\n") + "\n" + old, encoding="utf-8")
        self.commit_in(root, "Zones/" + ZONE, "%s, %s: older entries, for the history step" % (PROJECT, THREAD))

    def wrap_as(self, root, harness, entry, todo):
        """One wrap through the tool, as `harness` runs it: the assistant's words as JSON on standard input, the harness named
        in the environment, and its own memory folder for the pointer. Checks the receipt, the Resume here block, the commit
        and the pointer."""
        note = self.thread_note(root)
        rel = note.relative_to(root).as_posix()
        # Claude Code's memory folder is the one the tool knows; Codex documents none, so that wrap sends no pointer.
        memory = self.home / ".claude/projects/acceptance/memory"
        pointer = memory / "launch-plan.md"
        if harness == "claude":
            memory.mkdir(parents=True, exist_ok=True)
        words = {"zone": ZONE, "project": PROJECT, "thread": THREAD,
                 "resume": {"stands": "The board has decided; timing and budget are filled in and the outline waits for the distributor questions.",
                            "rows": {"Live artifact": "`Threads/Launch Plan/Outline.md`, the outline", "Rebuild with": "The sizing memo for the numbers",
                                     "Next action": NEXT_ACTION, "Keep in mind": "nothing", "Waiting on": "nobody", "Deadline": "none"}},
                 "entry": entry, "message": "%s, %s: wrapped through the tool as %s" % (PROJECT, THREAD, harness)}
        if harness == "claude":
            words["memory"] = {"path": str(pointer)}
        if todo:
            words["todo"] = {"add": ["[[%s]]: %s" % (THREAD, NEXT_ACTION)]}
        before = self.git(root, "Zones/" + ZONE, "rev-parse", "HEAD").stdout.strip()
        r = sh([sys.executable, root / "System" / "tools" / "wrap.py", "--json"], env=dict(self.env, GARRICK_HARNESS=harness), cwd=root,
               stdin=json.dumps(words), check=False)
        try:
            receipt = json.loads(r.stdout)
        except ValueError:
            raise Fail("the wrap as %s answered no receipt: %s" % (harness, (r.stderr or r.stdout).strip()[:160]))
        if r.returncode != 0 or receipt.get("outcome") != "saved":
            raise Fail("the wrap as %s was not saved: %s" % (harness, receipt.get("say")))
        after = self.git(root, "Zones/" + ZONE, "rev-parse", "HEAD").stdout.strip()
        if after == before or receipt.get("commit") != self.git(root, "Zones/" + ZONE, "rev-parse", "--short", "HEAD").stdout.strip():
            raise Fail("the wrap as %s made no commit that its receipt names" % harness)
        text = note.read_text(encoding="utf-8")
        if text.count("### Resume here") != 1 or "| Next action | %s |" % NEXT_ACTION not in text or entry not in text:
            raise Fail("the wrap as %s left the note without its Resume here block or its dated entry" % harness)
        if harness == "claude" and (not pointer.is_file() or "source: file:%s" % rel not in pointer.read_text(encoding="utf-8")):
            raise Fail("the wrap as %s left no memory pointer with its source in %s" % (harness, memory.name))
        if harness == "claude":
            moved_to = list((note.parent / "history").glob("*.md"))
            changed = self.git(root, "Zones/" + ZONE, "show", "--name-only", "--format=", "HEAD").stdout
            if not moved_to or "/history/" not in changed:
                raise Fail("the first wrap did not move old entries to history in its commit")

    def step_wrap(self, s):
        root = self.demo
        note = self.thread_note(root)
        rel = note.relative_to(root).as_posix()
        today = self.today
        said = "%d %s %d" % (today.day, today.strftime("%B"), today.year)
        if self.model == "claude":
            self.model_run("Wrap %s in the Birch zone. The next action is: %s" % (THREAD, NEXT_ACTION), root)
        else:
            self.seed_old_entries(root, note)
            self.wrap_as(root, "claude", "Wrapped by the acceptance run, as Claude Code would.", todo=True)
            self.wrap_as(root, "codex", "Wrapped by the acceptance run, as Codex would.", todo=False)
            s.note("the wrap ran twice through System/tools/wrap.py, as Claude Code and as Codex: each left a receipt of saved, a commit and the Resume here "
                   "block, and the Claude Code one a memory pointer the tool built; the first moved old entries to history in the same commit")
            s.note("the words of the wraps were written by a stand-in: no model chose them (skipped (stub))")
        done = list((root / "System" / "generated").glob("wrap-*.done"))
        if self.model != "claude" and not done:
            raise Fail("the wrap left no finished record in System/generated/")
        if self.git(root, "Zones/" + ZONE, "status", "--porcelain").stdout.strip():
            raise Fail("the wrap left changes uncommitted in the %s zone" % ZONE)
        self.state["wrapped"] = NEXT_ACTION if self.model != "claude" else None
        s.note("the wrap is committed in the %s zone, its lock is gone and its finished record is written" % ZONE)

    def step_restart(self, s):
        # The page is built by a process that ends. Starting it again is what the app does on a restart.
        before = (self.demo / "System" / "generated" / "status.html").stat().st_mtime
        time.sleep(1.1)
        self.build_page(self.demo)
        after = (self.demo / "System" / "generated" / "status.html").stat().st_mtime
        if after <= before:
            raise Fail("a new page builder did not write the page again")
        s.note("a fresh status.py process wrote the page again; the Ask server needs the jobs extra, which the demo does not install")

    def step_resume(self, s):
        root = self.demo
        sc = self.scope(root)
        rows = sc["mod"].resume_rows(self.thread_note(root))
        want = self.state.get("wrapped")
        if want is not None and rows.get("Next action") != want:
            raise Fail("the Resume here block's Next action is %r, not what the wrap wrote" % rows.get("Next action"))
        if not rows.get("Next action"):
            raise Fail("the Resume here block has no Next action")
        if want is not None:
            if "Wrapped by the acceptance run" not in self.thread_note(root).read_text(encoding="utf-8"):
                raise Fail("the wrap's dated entry is missing from the thread note")
            if NEXT_ACTION not in (root / "Zones" / ZONE / "Todo.md").read_text(encoding="utf-8"):
                raise Fail("the Next action has no line in the zone's Todo.md")
            if NEXT_ACTION.split(";")[0][:30] not in self.page(root):
                raise Fail("the rebuilt page does not show the thread's Next action")
        if re.search(r"status: *(parked|done)", self.thread_note(root).read_text(encoding="utf-8")):
            raise Fail("the wrapped thread is no longer active")
        s.note("Resume here and Next action read back as written: %r" % rows.get("Next action"))

    def step_correct(self, s):
        root = self.demo
        listing = sh([sys.executable, root / "System" / "tools" / "correct.py", "--root", root, "--old", OLD_FACT,
                      "--new", NEW_FACT, "--json"], env=self.env, cwd=root, check=False)
        try:
            copies = len(json.loads(listing.stdout)["hits"])
        except (ValueError, KeyError):
            copies = 0
        if listing.returncode != 0 or not copies:
            raise Fail("correct.py lists no live copy of %r: %s" % (OLD_FACT, (listing.stderr or listing.stdout).strip()[:160]))
        raw_before = {p: p.read_bytes() for p in (root / "Wikis" / "Meetings" / "raw").glob("*") if p.is_file()}
        if self.model == "claude":
            self.model_run("That's wrong: it's %s, not %s. Correct it everywhere." % (NEW_FACT, OLD_FACT), root)
        else:
            sh([sys.executable, root / "System" / "tools" / "correct.py", "--root", root, "--old", OLD_FACT, "--new", NEW_FACT,
                "--apply", "--why", "acceptance run", "--today", self.today.isoformat()], env=self.env, cwd=root)
        live = []
        for rel in ("Wikis/Meetings/wiki", "Zones", "System/context.md"):
            base = root / rel
            for p in ([base] if base.is_file() else sorted(base.rglob("*.md"))):
                if OLD_FACT in p.read_text(encoding="utf-8", errors="replace"):
                    live.append(p.relative_to(root).as_posix())
        if live:
            raise Fail("a live copy still holds the old value: %s" % live[0])
        if not any(NEW_FACT in p.read_text(encoding="utf-8", errors="replace")
                   for p in (root / "Wikis" / "Meetings" / "wiki" / "sources").glob("%s*.md" % SIDE_ACME)):
            raise Fail("the Meetings page does not hold the new value")
        for p, data in raw_before.items():
            if p.read_bytes() != data:
                raise Fail("a raw record was edited: %s" % p.name)
        for repo in ("Wikis", "Zones/Work"):
            if self.git(root, repo, "status", "--porcelain").stdout.strip():
                raise Fail("the correction left %s uncommitted" % repo)
        self.check(root)
        s.note("%d file(s) held the old value and none of the live ones does now; raw records are unchanged; check.py is clean" % copies)

    def step_update(self, s):
        tag = self.previous_tag()
        old = self.tag_tree(tag, "previous")
        target = self.tmp / "updating"
        sh([sys.executable, old / "install.py", "--config", old / "examples" / "acme.json", "--target", target],
           env=self.env, cwd=old, timeout=900)
        stamp_before = json.loads((target / "System" / "garrick-version.json").read_text(encoding="utf-8")).get("commit")
        sh([sys.executable, self.cand / "update.py", "--apply", "--yes", target], env=self.env, cwd=self.cand, timeout=900)
        stamp = json.loads((target / "System" / "garrick-version.json").read_text(encoding="utf-8"))
        if stamp.get("commit") == stamp_before:
            raise Fail("the installed and the updated version stamps are both %s: nothing was updated" % stamp_before)
        last = (stamp.get("updates") or [{}])[-1]
        if not last.get("to"):
            raise Fail("the update recorded no step in the version stamp")
        self.check(target)
        s.note("installed %s, updated it to %s; check.py is clean afterwards (stamp: %s to %s)"
               % (tag, self.commit, last.get("from"), last.get("to")))

    NAMES_FROM = "v0.76.0"      # the last release that keeps People and Aliases in System/context.md

    def step_names(self, s):
        """#653: a grown context.md (about 90 people and some aliases) of a workspace installed from v0.76.0, updated to the
        candidate and then given the yes (`--names --apply`). Every People and Aliases row stands in exactly one of
        System/context.md and System/names.md afterwards, names.md holds both tables, and context.md is under 8,000
        characters. Without the yes the update moves nothing."""
        old = self.tag_tree(self.NAMES_FROM, "names-previous")
        target = self.tmp / "names-ws"
        sh([sys.executable, old / "install.py", "--config", old / "examples" / "acme.json", "--target", target],
           env=self.env, cwd=old, timeout=900)
        ctx = target / "System" / "context.md"
        text = ctx.read_text(encoding="utf-8")
        first = ["Ada", "Bruno", "Carla", "Dario", "Edith", "Fabio", "Giulia", "Hugo", "Irene", "Jonas"]
        last = ["Aldous", "Brandt", "Corvin", "Delmar", "Estrin", "Farrow", "Gantry", "Holm", "Ibsen"]
        people = ["| %s %s | `%s` | %s |" % (f, l, "acme" if (i % 2) else "birch", "Contact %d at the client; leads one workstream of the supply-chain review and signs off its notes" % i)
                  for i, (f, l) in enumerate((f, l) for f in first for l in last)]
        aliases = ["| %s | %s %s |" % (("%s %s" % (f, l)).lower().replace("a", "ah", 1), f, l) for f, l in ((first[i], last[i % len(last)]) for i in range(8))]
        if "\n## People\n" not in text or "\n## Aliases\n" not in text:
            raise Fail("%s has no People or Aliases section in its context.md" % self.NAMES_FROM)
        def grow(txt, heading, rows):
            i = txt.index("\n## %s\n" % heading)
            j = txt.find("\n## ", i + 4)
            j = len(txt) if j < 0 else j
            return txt[:j].rstrip("\n") + "\n" + "\n".join(rows) + "\n" + txt[j:]
        text = grow(grow(text, "People", people), "Aliases", aliases)
        # A workspace from before the Learned column: the header has it, the older rows are one cell short, and the
        # rows added since carry it (#663).
        for old_head, new_head, rule in (("| Name | Party | Role |\n|---|---|---|", "| Name | Party | Role | Learned |\n|---|---|---|---|", None),
                                         ("| Heard | Means |\n|---|---|", "| Heard | Means | Learned |\n|---|---|---|", None)):
            if old_head not in text:
                raise Fail("%s has no table header %r in its context.md" % (self.NAMES_FROM, old_head.split("\n")[0]))
            text = text.replace(old_head, new_head, 1)
        text = text.replace("| Theo Marsh | `birch` | Managing partner |", "| Theo Marsh | `birch` | Managing partner | 2026-11-01, user |", 1)
        text = text.replace("| dana whitlaw | Dana Whitlock |", "| dana whitlaw | Dana Whitlock | 2026-11-01, user |", 1)
        ctx.write_text(text, encoding="utf-8")
        def norm(row):
            """A row as its cells, the empty ones at the end off: a short row and its padded form read the same."""
            cs = [c.strip() for c in row.strip().strip("|").split("|")]
            while cs and not cs[-1]:
                cs.pop()
            return "|".join(cs)
        def rows_of(txt):
            out, on = [], False
            for line in txt.split("\n"):
                if line.startswith("## "):
                    on = line.strip() in ("## People", "## Aliases")
                elif on and line.startswith("|") and not re.match(r"^\|[-| ]+\|\s*$", line) and line.split("|")[1].strip() not in ("Name", "Heard"):
                    out.append(line.rstrip())
            return out
        before = [norm(r) for r in rows_of(text)]
        if not any(r.count("|") == 4 for r in rows_of(text)) or not any(r.count("|") == 3 for r in rows_of(text)):
            raise Fail("the grown context.md has no short People or Aliases row to pad")
        if len(before) < 90 or len(text) < 8000:
            raise Fail("the grown context.md is not grown enough: %d rows, %d characters" % (len(before), len(text)))
        sh(["git", "-C", target, "add", "-A"], env=self.env, check=False)
        sh(["git", "-C", target, "commit", "-qm", "grow context.md"], env=self.env, check=False)
        sh([sys.executable, self.cand / "update.py", "--apply", "--yes", target], env=self.env, cwd=self.cand, timeout=900)
        if (target / "System" / "names.md").is_file() and rows_of((target / "System" / "names.md").read_text(encoding="utf-8")):
            raise Fail("the update moved People and Aliases without the yes")
        sh([sys.executable, self.cand / "install.py", "--update", target, "--names", "--apply"], env=self.env, cwd=self.cand, timeout=900)
        names = target / "System" / "names.md"
        if not names.is_file():
            raise Fail("System/names.md does not exist after --names --apply")
        raw_names = rows_of(names.read_text(encoding="utf-8"))
        wide = {"People": 4, "Aliases": 3}
        for table, count in wide.items():
            body = re.search(r"(?ms)^## %s\n(.*?)(?=^## |\Z)" % table, names.read_text(encoding="utf-8"))
            lines = [l for l in (body.group(1) if body else "").split("\n") if l.startswith("|")]
            if not lines or any(len(l.strip().strip("|").split("|")) != count for l in lines):
                raise Fail("a row of the %s table in names.md does not have the header's %d cells" % (table, count))
        in_names = [norm(r) for r in raw_names]
        in_context = rows_of(ctx.read_text(encoding="utf-8"))
        every = {}
        for row in in_names + in_context:
            every[row] = every.get(row, 0) + 1
        lost = [r for r in before if every.get(r, 0) != 1]
        if lost or len(in_names) != len(before) or in_context:
            raise Fail("%d row(s) are not in exactly one file (first: %s); names.md holds %d of %d, context.md still holds %d"
                       % (len(lost), (lost or [""])[0][:80], len(in_names), len(before), len(in_context)))
        size = len(ctx.read_text(encoding="utf-8"))
        if size >= 8000:
            raise Fail("context.md is %d characters after the move, not under 8,000" % size)
        self.check(target)
        s.note("a v0.76.0 workspace with %d People and Aliases rows: the update alone moved none; after --names --apply names.md holds all %d once, "
               "context.md holds none and is %d characters; check.py is clean" % (len(before), len(in_names), size))

    def step_hooks(self, s):
        """#670, #672: the settings name the zone guard and the read guard through `$HOME`, in a download of the previous release
        kept in the home folder. The update's report names each guard that differs and offers the refresh; an apply with nobody
        to ask copies nothing and names `--refresh-hooks`; an apply with the flag and stdin closed copies Garrick's own hook
        files (#680), and the settings file is the same bytes afterwards."""
        tag = self.previous_tag()
        old = self.tag_tree(tag, "hooks-previous")
        kept = self.home / "kept-garrick"
        shutil.copytree(old / "extras" / "hooks", kept / "extras" / "hooks")
        target = self.tmp / "hooks-ws"
        sh([sys.executable, old / "install.py", "--config", old / "examples" / "acme.json", "--target", target],
           env=self.env, cwd=old, timeout=900)
        settings = self.home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        entry = lambda name: {"hooks": [{"type": "command", "command": 'python3 "$HOME/kept-garrick/extras/hooks/%s"' % name}]}
        settings.write_text(json.dumps({"hooks": {"PreToolUse": [entry("zone_guard.py"), entry("read_guard.py")]}}), encoding="utf-8")
        before = settings.read_bytes()
        folder = kept / "extras" / "hooks"
        differing = [n for n in ("zone_guard.py", "read_guard.py", "parked_hint.py", "waiting_hook.py", "README.md")
                     if (folder / n).read_bytes() != (self.cand / "extras" / "hooks" / n).read_bytes()]
        if not differing:
            raise Fail("the previous release's hook files equal the candidate's: there is nothing to refresh")
        said = sh([sys.executable, self.cand / "update.py", target], env=self.env, cwd=self.cand, timeout=900, stdin="").stdout
        for name in [n for n in ("zone_guard.py", "read_guard.py") if n in differing]:
            line = "runs from ~/kept-garrick/extras/hooks/%s, which differs from this Garrick's" % name
            if line not in said:
                raise Fail("the update report does not name %s as another version's: %s" % (name, said.strip()[-300:]))
        # Both guards may be this release's and another hook file not (#672): the report then offers the refresh in its
        # second form, "The kept hooks at ... differ from this Garrick's in ...".
        offers = [o for o in ("Refresh the kept hooks at ~/kept-garrick/extras/hooks",
                              "The kept hooks at ~/kept-garrick/extras/hooks differ from this Garrick's in") if o in said]
        if not offers:
            raise Fail("the update report does not offer to refresh the kept hooks")
        if str(self.home) in said.split(offers[0], 1)[1]:
            raise Fail("the update report shows the home folder, not ~")
        applied = sh([sys.executable, self.cand / "update.py", "--apply", "--yes", target], env=self.env, cwd=self.cand,
                     timeout=900, stdin="").stdout
        if any((folder / n).read_bytes() == (self.cand / "extras" / "hooks" / n).read_bytes() for n in differing):
            raise Fail("the update copied hook files with nobody to ask")
        if "--refresh-hooks" not in applied:
            raise Fail("with nobody to ask and no flag, the update does not name --refresh-hooks: %s" % applied.strip()[-300:])
        # The yes an assistant's session passes (#680): stdin closed, and --refresh-hooks on the apply.
        r = sh([sys.executable, self.cand / "update.py", "--apply", "--yes", "--refresh-hooks", target], env=self.env,
               cwd=self.cand, timeout=900, stdin="", check=False)
        if "now holds this Garrick's" not in r.stdout:
            raise Fail("the refresh with --refresh-hooks said: %s" % (r.stdout or r.stderr).strip()[-300:])
        for n in differing:
            if (folder / n).read_bytes() != (self.cand / "extras" / "hooks" / n).read_bytes():
                raise Fail("%s in the kept folder is not this release's after the refresh" % n)
        if settings.read_bytes() != before:
            raise Fail("the refresh changed the assistant's settings")
        s.note("the settings name the zone guard and the read guard through $HOME in a kept download of %s: the report names %s as "
               "another version's and offers the refresh; with stdin closed and no flag nothing was copied and the flag was named; with "
               "--refresh-hooks and stdin closed %d hook file(s) match "
               "this release and the settings are unchanged" % (tag, ", ".join(n for n in differing if n.endswith("_guard.py")) or "no guard (another hook file differs)",
                       len(differing)))

    def step_refused(self, s):
        root = self.demo
        note = self.thread_note(root)
        head = self.git(root, "Zones/" + ZONE, "rev-parse", "HEAD").stdout.strip()
        original = note.read_text(encoding="utf-8")
        before = self.state.get("op_lines", 0)
        note.write_text(original + "\nSee [[Meetings/wiki/sources/%s|the renewal call]].\n" % SIDE_ACME, encoding="utf-8")
        try:
            req = json.dumps({"verb": "park", "zone": ZONE, "project": PROJECT, "thread": THREAD})
            r = sh([sys.executable, root / "System" / "status" / "page_action.py", "--workspace", root], env=self.env, cwd=root,
                   stdin=req, check=False)
            try:
                reply = json.loads(r.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise Fail("page_action.py gave no reply: %s" % (r.stderr or r.stdout).strip()[:160])
            if reply.get("ok"):
                raise Fail("the save was reported as made although the wall check refuses it")
            if not str(reply.get("say", "")).startswith(WALL_SAID):
                raise Fail("the save was refused, but not by the wall check: %r" % str(reply.get("say"))[:120])
            if reply.get("outcome") != "refused" or not reply.get("op"):
                raise Fail("the refusal carries no operation record of kind refused: %r" % (reply.get("outcome"),))
            if self.git(root, "Zones/" + ZONE, "rev-parse", "HEAD").stdout.strip() != head:
                raise Fail("the refused save reached the zone's history")
            if re.search(r"(?m)^status: *parked", note.read_text(encoding="utf-8")):
                raise Fail("the refused save left the thread parked")
            records = self.jobs / "operations.jsonl"
            lines = [json.loads(l) for l in records.read_text(encoding="utf-8").splitlines() if l.strip()] if records.is_file() else []
            mine = [l for l in lines if l.get("op") == reply.get("op")]
            if not mine or mine[-1].get("state") != "failed" or mine[-1].get("outcome") != "refused":
                raise Fail("the operation record of this save does not say failed and refused")
        finally:
            note.write_text(original, encoding="utf-8")
        self.build_page(root)
        if self.git(root, "Zones/" + ZONE, "status", "--porcelain").stdout.strip():
            raise Fail("the demo is not clean after the refused save was put back")
        s.note("the wall check refused the park: reply not ok, no commit, the thread still active, the record says refused")

    # -- the Ask set

    def scope(self, root):
        """The retrieval of a workspace, as its own copy of Ask has it, and no model."""
        key = str(root)
        cache = self.state.setdefault("scopes", {})
        if key not in cache:
            status = Path(root) / "System" / "status"
            if str(status) not in sys.path:
                sys.path.insert(0, str(status))
            ask = load_module("garrick_acc_ask_%d" % len(cache), status / "ask.py")
            sc = ask.scope_lib()
            lib = sc.lib(root)
            cache[key] = {"ask": ask, "mod": sc, "lib": lib, "ctx": lib.load_context(root)}
        return cache[key]

    def ask_one(self, root, q):
        """What Ask's retrieval admits for a question, in the order it ranks, and nothing from a model."""
        c = self.scope(root)
        sc, lib, ctx, ask = c["mod"], c["lib"], c["ctx"], c["ask"]
        names = ask.scan(root)
        row = {"id": q["id"], "outcome": "", "paths": [], "wall": False, "texts": []}
        try:
            named = sc.mentions(root, q["q"], names, ctx, lib)
            if named.question:
                row["outcome"] = "asks"
                return row
            find = dict(q["find"])
            if find.get("order") is None and sc.wants_recent(q["q"]):
                find["order"] = "recent"
            window = q.get("window")
            if find.get("route") in sc.ZONED and find.get("zone") is None and window:
                find["zone"] = window
            if isinstance(find.get("project"), str) and window and find["project"] not in names.get(window, {}):
                find.pop("project"), find.pop("thread", None)
            where = sc.scope(root, find, named, names, ctx, lib)
        except sc.Unclear:
            row["outcome"] = "asks"
            return row
        except sc.Refused:
            row["outcome"] = "asks"          # a question in no zone: the box asks which, and reads nothing
            return row
        records, back, matched = sc.choose(sc.search(root, where, ctx, lib), set(), ctx, lib)
        root_s = str(Path(root).resolve())
        row["paths"] = [str(r["path"]).replace(root_s + os.sep, "") for r in records]
        row["texts"] = [r.get("text", "") for r in records]
        row["wall"] = bool(back)
        row["outcome"] = "records" if records else "none"
        return row

    def judge(self, q, row):
        """The failures of one row against what the question expects: a list of short sentences."""
        want, bad = q.get("expect", {}), []
        if row["outcome"] != want.get("outcome", row["outcome"]):
            bad.append("outcome %s, expected %s" % (row["outcome"], want["outcome"]))
        paths = row["paths"]
        if want.get("first") and not (paths and want["first"] in paths[0]):
            bad.append("first record %s, expected one with %s" % (paths[0] if paths else "none", want["first"]))
        for part in want.get("any", []):
            if not any(part in p for p in paths):
                bad.append("no record with %s" % part)
        for part in want.get("none", []):
            hit = [p for p in paths if part in p]
            if hit:
                bad.append("admitted %s" % hit[0])
        if want.get("order") == "recent":
            days = [m.group(1) for m in (re.search(r"/sources/(\d{6})-", p) for p in paths) if m]
            if days != sorted(days, reverse=True):
                bad.append("the meetings are not newest first: %s" % ", ".join(days))
        if "wall" in want and row["wall"] != want["wall"]:
            bad.append("the wall %s, expected %s" % ("held a record back" if row["wall"] else "held none back", "one" if want["wall"] else "none"))
        text = "\n".join(row["texts"][:1]) if want.get("first") else "\n".join(row["texts"])
        for part in want.get("has", []):
            if part not in text:
                bad.append("the first record lacks %r" % part)
        for part in want.get("lacks", []):
            if part in text:
                bad.append("the first record still holds %r" % part)
        return bad

    def run_ask_set(self, root):
        qs = moved(json.loads(ASK_SET.read_text(encoding="utf-8"))["questions"], self.shift)
        rows = []
        for q in qs:
            try:
                row = self.ask_one(root, q)
                row["bad"] = self.judge(q, row)
            except Exception as exc:       # an older release's Ask: the row says so
                row = {"id": q["id"], "outcome": "error", "paths": [], "wall": False, "texts": [],
                       "bad": ["%s: %s" % (type(exc).__name__, str(exc)[:120])]}
            row["q"], row["kind"] = "%s (%s)" % (q["q"], q["window"] + " window" if q.get("window") else "no window"), q["kind"]
            if self.model == "claude" and q.get("cites"):
                row["cites"] = self.cited(root, q)
                row["bad"] += [c for c in row["cites"].get("missing", [])]
            rows.append(row)
        return rows

    def cited(self, root, q):
        win = root_zone(root, q["window"]) if q.get("window") else root
        out = self.model_run(q["q"] + " Answer from the records and name the pages you used.", win, timeout=600)
        missing = ["answer does not cite %s" % c for c in q["cites"] if c not in out]
        return {"missing": missing}

    def step_ask(self, s):
        rows = self.run_ask_set(self.demo)
        self.ask_rows = rows
        failed = [r for r in rows if r["bad"]]
        s.note("%d questions: %d as expected, %d not" % (len(rows), len(rows) - len(failed), len(failed)))
        if self.model != "claude":
            s.note("the cited sources of an answer need a model (skipped (stub)); the records Ask admits and ranks were checked")
        if self.args.compare:
            tree = self.tag_tree(self.args.compare, "compare")
            there = self.tmp / "demo-compare"
            sh([sys.executable, tree / "examples" / "demo" / "build.py", "--target", there, "--today", self.today.isoformat()],
               env=self.env, cwd=tree, timeout=1200)
            sh([sys.executable, there / "System" / "tools" / "correct.py", "--root", there, "--old", OLD_FACT, "--new", NEW_FACT,
                "--apply", "--why", "acceptance run", "--today", self.today.isoformat()], env=self.env, cwd=there, check=False)
            self.compared = (self.args.compare, self.run_ask_set(there))
        if failed:
            raise Fail("%s: %s" % (failed[0]["id"], "; ".join(failed[0]["bad"])))

    compared = None

    # -- the run

    def go(self):
        try:
            self.prepare()
        except Fail as exc:
            self.steps = [Step(k, k) for k in STEPS]
            for st in self.steps:
                st.status, st.why = "fail", "the candidate could not be prepared: %s" % exc
            return
        titles = {"install": "Install from the zip", "demo": "Build the demo", "file": "File one conversation",
                  "brief": "Ask for a brief", "wrap": "Wrap a thread", "restart": "Restart the page builder",
                  "resume": "Resume the thread", "correct": "Correct one fact", "update": "Update from the previous tag", "names": "Move People and Aliases to names.md",
                  "hooks": "Refresh the kept hooks",
                  "refused": "A refused save", "ask": "The fixed Ask set"}
        needs = {"file": "demo", "brief": "demo", "wrap": "demo", "restart": "demo", "resume": "wrap", "correct": "demo",
                 "refused": "demo", "ask": "demo"}
        chosen = self.args.steps.split(",") if self.args.steps else list(STEPS)
        for key in STEPS:
            st = Step(key, titles[key])
            self.steps.append(st)
            if key not in chosen:
                st.why = "not selected"
                continue
            need = needs.get(key)
            if need and need in self.failed:
                st.why = "needs the %s step, which failed" % need
                self.failed.add(key)            # what needs this step is blocked too
                continue
            if need and need not in chosen:
                st.why = "needs the %s step, which was not selected" % need
                continue
            t0 = time.time()
            try:
                getattr(self, "step_" + key)(st)
                st.status, st.why = "pass", "; ".join(st.notes)
            except Skip as exc:
                st.status, st.why = "skipped", str(exc)
            except Fail as exc:
                st.status, st.why = "fail", str(exc)
                self.failed.add(key)
            except subprocess.TimeoutExpired as exc:
                st.status, st.why = "fail", "timed out: %s" % " ".join(str(c) for c in exc.cmd[:3])
                self.failed.add(key)
            except Exception as exc:                      # a step must never end the run without a verdict
                st.status, st.why = "fail", "%s: %s" % (type(exc).__name__, str(exc)[:200])
                self.failed.add(key)
            st.seconds = time.time() - t0

    def report(self):
        mark = {"pass": "pass", "fail": "FAIL", "skipped": "skipped"}
        lines = ["# Acceptance run", "",
                 "- Candidate: %s" % self.commit,
                 "- Model: %s%s" % (self.model, " (steps that need a model use a stand-in, and the report says which part)" if self.model == "stub" else ""),
                 "- Run: %s, %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), sys.platform), "",
                 "| Step | Result | Why |", "|---|---|---|"]
        for st in self.steps:
            lines.append("| %s | %s | %s |" % (st.title, mark[st.status], st.why.replace("|", "/").replace("\n", " ")))
        failed = [s.title for s in self.steps if s.status == "fail"]
        skipped = [s.title for s in self.steps if s.status == "skipped"]
        head = ("FAILED at: " + ", ".join(failed)) if failed else \
            ("Passed, with %d skipped: %s" % (len(skipped), ", ".join(skipped)) if skipped else "Passed")
        lines += ["", "**%s.** %d passed, %d failed, %d skipped." % (head, sum(s.status == "pass" for s in self.steps), len(failed), len(skipped))]
        if skipped:
            lines.append("Skipped: " + "; ".join("%s (%s)" % (s.title, s.why) for s in self.steps if s.status == "skipped"))
        if self.ask_rows:
            lines += ["", "## The Ask set", ""]
            if self.compared:
                tag, other = self.compared
                lines += ["| Question | Kind | Candidate | %s |" % tag, "|---|---|---|---|"]
                by = {r["id"]: r for r in other}
                for r in self.ask_rows:
                    lines.append("| %s | %s | %s | %s |" % (r["q"], r["kind"], summary(r), summary(by.get(r["id"]))))
            else:
                lines += ["| Question | Kind | Candidate |", "|---|---|---|"]
                for r in self.ask_rows:
                    lines.append("| %s | %s | %s |" % (r["q"], r["kind"], summary(r)))
        return "\n".join(lines) + "\n"


def summary(row):
    if row is None:
        return "no row"
    head = row["outcome"] + (", first %s" % row["paths"][0].split("/")[-1] if row["paths"] else "") + \
        (", wall held a record back" if row["wall"] else "")
    return ("FAIL: " + "; ".join(row["bad"]) + " (" + head + ")") if row["bad"] else head


def root_zone(root, zone):
    return Path(root) / "Zones" / zone


def shutil_which(cmd):
    return shutil.which(cmd)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The acceptance run: install, demo, file, brief, wrap, resume, correct, update, "
                                             "a refused save and the Ask set, on a release candidate.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--candidate", metavar="ZIP", help="a release zip, git archive --format=zip --prefix=garrick/")
    src.add_argument("--commit", metavar="REF", help="a commit of this clone (default HEAD), archived the same way")
    ap.add_argument("--model", choices=("stub", "claude"), default="stub")
    ap.add_argument("--report", metavar="FILE", help="write the Markdown report here")
    ap.add_argument("--compare", metavar="TAG", help="run the Ask set on this tag too, and show both side by side")
    ap.add_argument("--previous", metavar="TAG", help="the tag the update step starts from (default: the newest other tag)")
    ap.add_argument("--steps", metavar="LIST", help="only these steps, comma-separated: " + ", ".join(STEPS))
    ap.add_argument("--workdir", metavar="DIR", help="work in this folder instead of a temporary one, and keep it")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any step is skipped, as well as when one fails")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = ap.parse_args(argv)
    if args.steps:
        bad = [s for s in args.steps.split(",") if s not in STEPS]
        if bad:
            ap.error("not a step: %s" % ", ".join(bad))
    run = Run(args)
    try:
        run.go()
        text = run.report()
    finally:
        if not (args.keep or args.workdir):
            shutil.rmtree(run.tmp, ignore_errors=True)
    print(text)
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    bad = {"fail", "skipped"} if args.strict else {"fail"}
    return 1 if any(s.status in bad for s in run.steps) else 0


if __name__ == "__main__":
    sys.exit(main())
