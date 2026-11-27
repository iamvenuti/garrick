#!/usr/bin/env python3
"""run_op.py: carries out one prepared operation as a process of its own, and writes the receipt.

    python3 run_op.py STATE_FOLDER OPERATION_ID

The service starts it detached at `execute` and returns at once, because a commit and its wall check can take up to
five minutes, which is longer than a client waits for a tool call. It lives on if the service restarts. It holds
`<id>.run`, a lock the whole run, so that `status` can tell a worker that is gone from one that is slow (as
operations.py does for a click), and it writes the receipt into the operation's record before it ends.

The work is a process of its own again: the workspace's page_action.py as a click runs it, with `--via remote`, or,
for a checkpoint, the thread tool scaffold.py as a session runs it. This module never imports page_action.py.

Standard library only, so that it runs on the Python macOS ships.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

VIA = "remote"
PAGE_PYTHON = "/usr/bin/python3"
RUN_TIMEOUT = 420           # seconds: the lock wait (45), a commit and its wall check (300), and slack
LINE_VERBS = ("todo-done", "todo-undo", "todo-date", "todo-edit", "todo-retire")
JSON_VERBS = ("note-add", "todo-add", "park", "wake")
LONG_WAY = "It took longer than expected and may or may not have been saved. Check the zone at the Mac before trying again."
CRASHED = "The save did not finish. Nothing more was done. Check the zone at the Mac before trying again."


ASK = (
    "import json, runpy, sys\n"
    "m = runpy.run_path(sys.argv[1])\n"
    "if not callable(m.get('outcome')) or not callable(m.get('prepare')):\n"
    "    sys.exit(3)\n"
    "print(json.dumps(m['outcome'](sys.argv[2], sys.argv[3], False)))\n")


def core_outcome(ws, repo, op: str):
    """What the workspace's own commit record says became of `op` in `repo`: the receipt as a dict, or None when there is none to read
    (an operations.py without the record's calls, no record of this operation, a repository git cannot read). Run as a process of its
    own, as page_action.py is: the service never loads the core's code into itself."""
    path = Path(ws) / "System" / "tools" / "operations.py"
    if not path.is_file():
        return None
    try:
        done = subprocess.run([python(), "-I", "-c", ASK, str(path), str(repo), op], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, cwd=str(ws))
        got = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def python() -> str:
    return PAGE_PYTHON if os.access(PAGE_PYTHON, os.X_OK) else sys.executable


def command(ws: str, rec: dict):
    """(argv, the standard input) of one operation. The request is built here from the record's own fields and
    never from anything else: a field the verb does not take is not sent, and `confirm`, `file`, `key` and
    `destination` are never sent by a model."""
    verb, zone, f = rec["verb"], rec["zone"], rec.get("fields") or {}
    page = str(Path(ws) / "System" / "status" / "page_action.py")
    base = [python(), page, "--workspace", ws, "--via", VIA]
    if verb in LINE_VERBS:
        argv = base + [verb, "--zone=" + zone, "--file=Todo.md", "--line=" + f["line"], "--op=" + rec["id"]]   # the same id the record is read by
        for field in ("date", "text", "reason"):
            if f.get(field) is not None and field in LINE_FIELDS[verb]:
                argv.append("--%s=%s" % (field, f[field]))
        return argv, None
    if verb == "checkpoint":
        req = {"verb": "checkpoint", "zone": zone, "project": f["project"]}
        for field in ("thread", "items", "drop"):
            if f.get(field):
                req[field] = f[field]
        return [python(), str(Path(ws) / "System" / "tools" / "scaffold.py"), "--root", ws, "checkpoint"], json.dumps(req)
    req = {"verb": verb, "zone": zone, "op": rec["id"]}
    for field in ("project", "thread", "text", "title", "target", "date"):
        if f.get(field) is not None:
            req[field] = f[field]
    return base, json.dumps(req)


LINE_FIELDS = {"todo-done": (), "todo-undo": (), "todo-date": ("date",), "todo-edit": ("text",), "todo-retire": ("reason",)}


def with_state(argv, stdin, env, ws):
    """A checkpoint says what it read last: the hash of the Resume here block and the key of the checkpoint now in the
    note, which scaffold.py compares again at the write. It is read just before the write, never taken from the model."""
    req = json.loads(stdin)
    look = dict(req, read=True)
    for k in ("items", "drop"):
        look.pop(k, None)
    got = subprocess.run(argv, input=json.dumps(look), capture_output=True, text=True, timeout=120, env=env, cwd=ws)
    try:
        state = json.loads(got.stdout)
    except ValueError:
        return stdin
    if isinstance(state, dict):
        req["base"], req["prev"] = state.get("base"), state.get("key")
    return json.dumps(req)


REPEAT_DONE = "This was already done a few minutes ago. Nothing was saved again."
REPEAT_RUNNING = "The same request is still running. Nothing was sent again."


RUNNING_START = "The same request is still running"      # how the page action opens a repeat of a request that has not ended
QUESTIONS = ("Do you want it done a second time?", "Do you want it done a second time once that one ends?")


def repeat_receipt(reply, text: str, code: int = 1):
    """A repeat that the page action's record answers with a question ("Do you want it done a second time?") is a
    plain receipt here: nothing ran, nothing was saved, and no model can answer the question, so none is passed on."""
    asked = isinstance(reply, dict) and (reply.get("state") == "asked" or "again" in reply)
    if isinstance(reply, dict):
        said = str(reply.get("say") or "")
        if not asked:
            return None                  # a reply that parses is decided by its own fields, never by the words a line carries
    else:
        said = text
        if code == 0 or not text.rstrip().endswith(QUESTIONS):
            return None                  # plain text: only a failed run that ends with the fixed question
    return {"ok": False, "say": REPEAT_RUNNING if said.lstrip().startswith(RUNNING_START) else REPEAT_DONE}


def receipt(verb: str, code: int, out: str, err: str) -> dict:
    """What came back, as a receipt: whether it saved, in the words of the tool, and the commit when it names one."""
    out, err = (out or "").strip(), (err or "").strip()
    try:
        first = json.loads(out) if out.startswith("{") else None
    except ValueError:
        first = None
    made = repeat_receipt(first, out if code == 0 else (err or out), code)
    if made is not None:
        return made
    if verb == "checkpoint" or (out.startswith("{") and verb in JSON_VERBS):
        try:
            reply = json.loads(out)
        except ValueError:
            reply = None
        if isinstance(reply, dict):
            say = str(reply.get("say") or "").strip() or ("Done." if reply.get("ok") else "That was refused.")
            made = {"ok": bool(reply.get("ok")), "say": say[:600]}
            if verb == "checkpoint":
                made["wrote"] = bool(reply.get("wrote"))
            if reply.get("commit"):
                made["commit"] = str(reply["commit"])[:64]
            return made
    text = out if code == 0 else (err or out)
    undo = re.search(r"--commit ([0-9a-f]{7,40})", text)
    say = text.split("\nTo undo:")[0].strip()
    made = {"ok": code == 0, "say": (say or ("Done." if code == 0 else "That was refused."))[:600]}
    if undo and code == 0:
        made["commit"] = undo.group(1)
    return made


def write(path: Path, rec: dict) -> None:
    tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(str(tmp), str(path))


def keep_checkpoint(state: Path, rec: dict, ws: str) -> None:
    """The note a checkpoint wrote, as it stands now. The note is uncommitted until the next wrap, and the next
    checkpoint may write over it only while it is exactly this."""
    import hashlib
    f = rec.get("fields") or {}
    rel = ("%s/Threads/%s/%s.md" % (f["project"], f["thread"], f["thread"])) if f.get("thread") else "%s/%s.md" % (f["project"], f["project"])
    try:
        sha = hashlib.sha256((Path(ws) / "Zones" / rec["zone"] / rel).read_bytes()).hexdigest()
        file = state / "operations" / "checkpoints.json"
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data["%s/%s/%s" % (rec["grant"], rec["zone"], rel)] = sha
        write(file, data)
    except OSError:
        pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    state, op = Path(argv[0]), argv[1]
    if not re.fullmatch(r"[0-9a-f]{16}", op):
        return 2
    folder = state / "operations"
    path = folder / (op + ".json")
    run = os.open(str(folder / (op + ".run")), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(run, fcntl.LOCK_EX)                         # held for the whole run, gone with the process
    rec = json.loads(path.read_text(encoding="utf-8"))
    if rec.get("state") != "running":
        return 0
    ws = rec["workspace"]
    argv_, stdin = command(ws, rec)
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "GARRICK_JOBS_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM",
            "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    state_now, made = "failed", None
    try:
        if rec["verb"] == "checkpoint":
            stdin = with_state(argv_, stdin, env, ws)
        done = subprocess.run(argv_, input=stdin, capture_output=True, text=True, timeout=RUN_TIMEOUT, env=env, cwd=ws)
        made = receipt(rec["verb"], done.returncode, done.stdout, done.stderr)
        state_now = "saved" if made["ok"] else "refused"
    except subprocess.TimeoutExpired:
        state_now, made = "unknown", {"ok": False, "say": LONG_WAY}
    except OSError:
        made = {"ok": False, "say": CRASHED}
    if rec["verb"] == "checkpoint" and made and made.get("ok"):
        keep_checkpoint(state, rec, ws)
    fresh = json.loads(path.read_text(encoding="utf-8"))
    fresh.update({"state": state_now, "receipt": made, "finished": time.time()})
    fresh.pop("fields", None)                               # the words are kept only while there is work to do
    fresh.pop("would", None)
    write(path, fresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
