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

STEPS = ("install", "demo", "file", "brief", "wrap", "restart", "resume", "correct", "update", "refused", "ask")
# The demo's thread this run wraps, the call it files, and the fact it corrects.
ZONE, PROJECT, THREAD = "Birch", "Birch Entry", "Launch Plan"
SIDE_ACME, SIDE_BIRCH = "261027-cobalt-renewal-for-acme", "261103-cobalt-northern-lane-for-birch"
OLD_FACT, NEW_FACT = "twelve hundred pallets", "fourteen hundred pallets"
NEXT_ACTION = "Send Ruth the distributor questions before her first call; Sam's."
HOST_JOB = "zz-host-nightly"
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
        version = (self.cand / "VERSION").read_text(encoding="utf-8") if (self.cand / "VERSION").is_file() else ""
        # The newest tag that is not the candidate's own.
        for t in tags:
            if "tag: %s" % t not in version:
                return t
        return tags[0]

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

    def step_wrap(self, s):
        root = self.demo
        note = self.thread_note(root)
        rel = note.relative_to(root).as_posix()
        today = self.today
        said = "%d %s %d" % (today.day, today.strftime("%B"), today.year)
        if self.model == "claude":
            self.model_run("Wrap %s in the Birch zone. The next action is: %s" % (THREAD, NEXT_ACTION), root)
        else:
            sh([sys.executable, root / "System" / "tools" / "wrap_lock.py", "start", rel], env=self.env, cwd=root)
            try:
                text = note.read_text(encoding="utf-8")
                start = text.index("**Where it stands,")
                end = text.index("\n---\n", start)
                block = ("**Where it stands, %s.** The board has decided; timing and budget are filled in and the outline waits for the "
                         "distributor questions.\n\n| | |\n|---|---|\n| Live artifact | `Threads/Launch Plan/Outline.md`, the outline |\n"
                         "| Rebuild with | The sizing memo for the numbers |\n| Next action | %s |\n| Waiting on | nobody |\n"
                         "| Deadline | none |\n" % (said, NEXT_ACTION))
                text = text[:start] + block + text[end:]
                text = text.replace("\n---\n", "\n---\n\n**%s.** Wrapped by the acceptance run.\n" % said, 1)
                text = re.sub(r"(?m)^updated: .*$", "updated: %s" % today.isoformat(), text, count=1)
                note.write_text(text, encoding="utf-8")
                todo = root / "Zones" / ZONE / "Todo.md"
                t = todo.read_text(encoding="utf-8")
                t = t.replace("\n## Done", "- [ ] [[%s]]: %s\n\n## Done" % (THREAD, NEXT_ACTION), 1) if "\n## Done" in t else t
                todo.write_text(t, encoding="utf-8")
                self.commit_in(root, "Zones/" + ZONE, "%s, %s: wrapped" % (PROJECT, THREAD))
            finally:
                sh([sys.executable, root / "System" / "tools" / "wrap_lock.py", "end", rel], env=self.env, cwd=root, check=False)
            s.note("the wrap was written by a stand-in: no model chose its words (skipped (stub))")
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
            if "Next action" not in self.page(root) and NEXT_ACTION.split(";")[0][:30] not in self.page(root):
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
        sh([sys.executable, self.cand / "update.py", "--apply", "--yes", target], env=self.env, cwd=self.cand, timeout=900)
        stamp = json.loads((target / "System" / "garrick-version.json").read_text(encoding="utf-8"))
        last = (stamp.get("updates") or [{}])[-1]
        if not last.get("to"):
            raise Fail("the update recorded no step in the version stamp")
        self.check(target)
        s.note("installed %s, updated it to %s; check.py is clean afterwards (stamp: %s to %s)"
               % (tag, self.commit, last.get("from"), last.get("to")))

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
            if reply.get("outcome") not in (None, "refused"):
                raise Fail("the save ended as %r, not as refused" % reply.get("outcome"))
            if self.git(root, "Zones/" + ZONE, "rev-parse", "HEAD").stdout.strip() != head:
                raise Fail("the refused save reached the zone's history")
            if re.search(r"(?m)^status: *parked", note.read_text(encoding="utf-8")):
                raise Fail("the refused save left the thread parked")
            records = (self.jobs / "operations.jsonl")
            if records.is_file():
                last = [json.loads(l) for l in records.read_text(encoding="utf-8").splitlines() if l.strip()][-1]
                if last.get("state") == "completed":
                    raise Fail("the operation record of the refused save says completed")
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
        qs = json.loads(ASK_SET.read_text(encoding="utf-8"))["questions"]
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
                  "resume": "Resume the thread", "correct": "Correct one fact", "update": "Update from the previous tag",
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
        lines += ["", "**%s.** %d passed, %d failed, %d skipped." % (
            "FAILED at: " + ", ".join(failed) if failed else "Passed",
            sum(s.status == "pass" for s in self.steps), len(failed), len(skipped))]
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
    return 1 if any(s.status == "fail" for s in run.steps) else 0


if __name__ == "__main__":
    sys.exit(main())
