#!/usr/bin/env python3
"""operations.py: the durable record of what state a page action is in.

The status page's buttons (page_action.py, in the status extra) run each
click as its own process. This module gives each of those a record that
outlives the process and the page: one JSON object per line, appended to
`operations.jsonl` in the jobs folder (GARRICK_JOBS_DIR, or
~/Library/Logs/garrick-jobs on a Mac), beside the locks and the audit log.
That folder is outside the workspace, so the record is never committed and
never appears in Obsidian. The notes and git stay the only record of *what
changed*; this is the record of *what state an action is in*.

Two ids, each with one job:

    op   a correlation id, 8 to 32 lowercase hex characters, minted by the
         caller so the page can show the action within a second of the click.
         Checked for shape only; never trusted for meaning.
    key  an identity key, computed here from the verb, the zone and the
         verb's declared identity fields. A client cannot choose or defeat
         it. It recognises a repeated click.

Four states: `queued`, `running` (with a free-text `phase` the worker
writes), then `completed` or `failed`. Every terminal record carries an
`outcome`, and only one of them may read as saved:

    saved      completed   the edit was made and committed
    refused    failed      a check said no: a wall, a stale line, a collision
    crashed    failed      the worker raised, or git failed for another reason
    unknown    failed      the worker is gone and left no terminal record
    lost       failed      the record could not be read (the page's own entry)

The sentences for the four that failed come from one mapping, `say()`, keyed
by outcome; nothing else composes a terminal sentence, and a reason that
would read as a success is replaced before it reaches one (`affirms()`).

Whether a worker is alive is a lock file, `op-<op>.run`, held with a
non-blocking exclusive flock for the whole run: it survives pid reuse and
goes with the process on SIGKILL. A record that is not terminal whose lock
can be taken has no worker, and the next reader writes `unknown` for it.

A request that repeats one the record holds is not simply run again. Inside
IDEM_WINDOW, a double click, it joins the first or gets its saved result back;
past it, until LOOKBACK, it is told what was done and when and asked whether
it is meant a second time, and only a request whose `confirm` names that
action runs again (`repeats()`, `asked()`). The numbers that decide it, and
every client's wait they are derived from, are the clock below.

`DECLARED` is the table every operation is declared in, one row per verb,
whichever way the request arrives: the page's buttons, the ask box, a skill
piping JSON into page_action.py, or scaffold.py on the command line. A row
names the `fields` a request may carry, the `identity` among them, the
`scope` it touches, whether it `commits`, whether a `retry` of it is safe,
and the `precheck` that says what must still be true for it to run.

Validation is closed: `validate()` refuses a field the verb does not declare,
by name, rather than ignoring it, so an unknown field can never widen what an
action touches. The reason comes from this file, so the sentence read for a
refusal is the same whichever way the request arrived.

`stale()` is the other half: given the fingerprint read from the world now,
it says whether the request still means what it did. Nothing here computes a
fingerprint. The Todo verbs' is the hash of the line's exact text, which
todo_lines keeps; park's and wake's is the note's own `status:`.

A tick or an untick may name several lines at once, as `keys` in place of
`key` (#107): the page batches the ticks made within a few seconds of each
other into one request, one lock, one edit and one commit. Its record is one
entry that lists every line, so a reload knows which rows are pending, and
a batch of one is the same request as the line named by `key`.

`WALL_REFUSAL` is the sentence the rule gives for a wall that held something
back (#116). Any action the zone's wall check refused ends on it word for
word (#107, #172): say() adds no refusal wording of its own to it.

`OPS` is the verbs that keep a durable record, derived from the table: six
since 0.26.0, and `note-add`, `todo-edit` and `todo-retire` since 0.82.0, so
that a retry from a caller that cannot see its first answer is joined, not
done twice (#701). A newer copy of this file found by an older
status extra must not start recording verbs that extra knows nothing about.
`checkpoint` is declared and deliberately left out of `RECORDED`: it keeps no
journal entry and does not use `IDEM_WINDOW`, because it has state of its own
to compare a repeat against, the block already in the thread note.

The commit record (0.84.0, #716). The journal above says what state an action
is in while it runs. It is outside the workspace and says nothing about git.
Every verb whose row has `commits` also gets a second record, in the
repository it changes, which settles from git's own history. The calls:

    prepare(repo, verb, req, op="", via="", workspace="") -> receipt
        Before the commit. Writes `<git dir>/garrick-ops/<op>.json`: the
        operation id, the verb, the zone, a hash of every declared field of
        the request (`payload`), a fingerprint of the target (the repository's
        HEAD, `head`), the caller (`via`), the times and the state. It holds no
        note text and no Todo line text: hashes, the verb and ids only. It
        lives in the zone's own git directory, so it moves with the zone, is
        never committed, and is never read by a session in another zone.
        The same op with the same request returns what the first one did; the
        same op with another request raises BadOp. Raises BadOp for a record
        whose seal does not match its fields (a forged or hand-edited one).
    execute(repo, op, work) -> (what work returned, receipt)
        Takes the operation's run lock, marks it `running`, calls
        `work(trailers)`, and settles from git whatever work did, a raise
        included. `trailers` is the text the commit must carry as a second
        message paragraph (`git commit -m <message> -m <trailers>`): the
        commit then names the operation and the payload, so git's history is
        the evidence of whether it committed.
    settle(repo, op, ran_ok=None) -> receipt
        Reads git and writes the operation's settled state: `done` (one commit
        carries this op and this payload; or, for a run that reported success
        and moved HEAD without trailers, that HEAD), `not-done` (no commit with
        the id, HEAD where it was), or `unsure` (a commit with the id and
        another payload, two commits with it, HEAD moved by something else, or
        a repository that cannot be read), always naming the commits found.
        Run by the caller that finishes, and by the next run for a worker that
        died: `outcome()` and `sweep()`.
    outcome(repo, op) -> receipt
        The reader. A `running` operation whose worker is gone is settled from
        git first. `new` is true on the first report of a settlement made by a
        later run, and false on every one after: each case is said once.
    sweep(repo) -> [receipt]
        Every operation in the repository that a dead worker left `running`,
        settled; only the ones not reported before are returned.

A receipt is a dict: `op`, `verb`, `zone`, `state` (`prepared`, `running` or
`settled`), `result` (None, `done`, `not-done` or `unsure`), `commit` (the
commit found or made, or ""), `found` (every commit that carries the op),
`run` (may the caller run the work now), `new`, `recorded` (false when the
repository cannot be read: nothing was recorded, and the caller does what it
did before) and `say`, a plain sentence. `unsure` never runs: the same op is
refused until a person has looked, and nothing is done twice. A `not-done`
operation may be run again under the same op. A settled `done` operation
returns its first receipt and never a second commit.

An older operations.py has none of these calls, and an older page_action.py
never makes them: each side checks for the other (`hasattr`) and carries on as
0.83.0 did.

The table declares; the handlers do the work, and do not move here.
Standard library only; Python 3.9.
"""

from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import fcntl
except ImportError:             # not on Windows, where the status app does not run
    fcntl = None

API = 1
FILE = "operations.jsonl"
JOURNAL_LOCK = "operations.lock"

# ---- the clock ------------------------------------------------------------
# Every number that decides how long a request may take, how long whoever sent
# it waits, and so whether a request sent again is the one already made, in
# one place, each derived from the ones above it (#137). page_action.py and
# ask.py, in the status extra, take theirs from here; Garrick.app cannot read
# Python, so it holds a copy of APP_WAIT that a test holds to this one.
#
#   the work     GIT_TIMEOUT and COMMIT_TIMEOUT bound what one action takes,
#                and TURN_TIMEOUT one turn of the ask session
#   the clients  ASK_WAIT and APP_WAIT: how long the ask box waits, which has
#                to be as long as the slowest request can take, or the box gives
#                up while the commit is still running and invites a second one
#   the record   IDEM_WINDOW: a double click. Inside it a repeated request
#                joins the one under way, or is answered with its save, and
#                nothing runs. LOOKBACK: past the window and up to this long
#                after the first one ended, a repeat is not run either. It is
#                told what was done and when, and asked; only a request that
#                carries `confirm` naming that action runs a second time. It
#                covers the longest a client can wait, so the retry a client
#                that gave up prompts is always one the record recognises.
GIT_TIMEOUT = 60                # seconds: one git command
COMMIT_TIMEOUT = 300            # seconds: a commit, its hooks and the zone's wall check (#76)
TURN_TIMEOUT = 60               # seconds: one turn of the ask session
ASK_WAIT = 2 * TURN_TIMEOUT + COMMIT_TIMEOUT + GIT_TIMEOUT     # 480: ask.py, for its server
APP_WAIT = ASK_WAIT + 30        # 510: Garrick.app, for ask.py, so that ask.py's own message comes first
IDEM_WINDOW = 120               # seconds: a double click, joined or answered with its save
LOOKBACK = APP_WAIT             # seconds after the first one ended: asked about, never run unasked
RECENT = 600                    # seconds: a terminal record is still offered to a page for this long
KEEP = 86400                    # seconds: and kept in the file for this long
COMPACT_BYTES = 512 * 1024
LOGGED_TEXT = 60                # a new line's text, cut as the audit log cuts it
OP_RE = re.compile(r"[0-9a-f]{8,32}")

STATES = ("queued", "running", "completed", "failed")
# Who sent a request, named in its record and in the audit log (#344): a click
# on the page, the ask box, an assistant's session at the command line, the outbox, or a remote assistant.
CALLERS = ("page", "ask", "session", "outbox", "remote")
OUTCOMES = ("saved", "refused", "crashed", "unknown", "lost")
SUCCESS_VERBS = ("saved", "parked", "ticked", "added", "renamed", "made", "committed")

# ---- the declared operations ---------------------------------------------

Op = collections.namedtuple("Op", "fields identity scope commits retry precheck")
# Per verb:
#   fields    every field a request may carry besides those in ALWAYS. A field
#             not here is refused by name (validate), never ignored.
#   identity  which of them say what the request is, so that the same request
#             twice has the same key. The zone is always part of it besides.
#   scope     what a request of this verb may touch: one zone's notes, the
#             workspace outside a zone, the machine, or nothing (it reads).
#   commits   whether it makes a commit in a zone's repository.
#   retry     whether sending it again after it failed can do a second thing.
#             "safe": the handler checks the world before it changes it.
#   precheck  the fingerprint the request must still match (stale), or None
#             where the handler checks for itself.
SCOPES = ("zone", "workspace", "machine", "none")
RETRIES = ("safe", "unsafe")
PRECHECKS = (None, "line", "status", "checkpoint")
# The fields every request may carry, whatever its verb: what it is, and the
# correlation id the caller mints for it.
ALWAYS = ("verb", "op")


def _op(fields, identity=(), scope="none", commits=False, retry="unsafe", precheck=None) -> Op:
    return Op(fields=tuple(fields), identity=tuple(identity), scope=scope, commits=commits,
              retry=retry, precheck=precheck)


DECLARED: Dict[str, Op] = {
    # The six the page sends under the zone lock, and the only ones that keep
    # a record. Their prechecks are this file's; the rest check for themselves.
    # Each may carry `confirm`, naming the earlier action it was asked about
    # (start()), and never part of what the request is.
    "park": _op(("zone", "project", "thread", "file", "confirm"), ("project", "thread", "file"),
                "zone", True, "safe", "status"),
    "wake": _op(("zone", "project", "thread", "file", "confirm"), ("project", "thread", "file"),
                "zone", True, "safe", "status"),
    # A tick or an untick names its line by `key`, or several by `keys`, a
    # batch the page sends as one request (#107); never both.
    "todo-done": _op(("zone", "file", "key", "keys", "confirm"), ("file", "key", "keys"), "zone", True, "safe", "line"),
    "todo-undo": _op(("zone", "file", "key", "keys", "confirm"), ("file", "key", "keys"), "zone", True, "safe", "line"),
    "todo-date": _op(("zone", "file", "key", "date", "confirm"), ("file", "key", "date"), "zone", True, "safe", "line"),
    # The line it adds has no key yet: a line already in the note is refused
    # by the handler, which is that verb's own check.
    "todo-add": _op(("zone", "text", "target", "date", "confirm"), ("text", "target", "date"), "zone", True, "safe"),
    # Distil (#591): reword an open line, or move it to the expired archive with its source. By key, as a tick is, so a
    # line that has moved is refused. They keep a journal record since 0.82.0, as note-add does (#701).
    "todo-edit": _op(("zone", "file", "key", "text", "confirm"), ("file", "key", "text"), "zone", True, "safe", "line"),
    "todo-retire": _op(("zone", "file", "key", "reason", "confirm"), ("file", "key", "reason"), "zone", True, "safe", "line"),
    # A note to yourself (#569): the text goes into a dated file under the thread or project it is about, its actions
    # into that zone's Todo.md, one commit. The place is a `destination`, as the owner would say it, or the `zone`,
    # `project` and `thread` the ask box has checked; the handler refuses one that does not settle to one folder.
    # A second run writes a second note, so a retry is not safe.
    "note-add": _op(("zone", "project", "thread", "destination", "text", "title", "confirm"),
                    ("project", "thread", "destination", "text"), "zone", True),
    # Declared, and nothing else: each of these keeps the validation it has.
    # They are here so that one table answers what a verb accepts, and so the
    # test that enumerates what the page sends has something to check against.
    "new-project": _op(("zone", "name", "party", "thread", "spoken", "thread_spoken",
                        "heading",
                        ), ("name",), "zone", True, "safe"),
    # The same, with a party added first on the user's own choice in the page's dialog (#522): `perform` refuses it
    # from any caller but the page.
    "new-project-party": _op(("zone", "name", "thread", "spoken", "thread_spoken", "new_party", "party_what",
                              "heading",
                              ), ("name",), "zone", True, "safe"),
    "new-thread": _op(("zone", "project", "name", "spoken",
                       "papers",
                       ), ("project", "name"), "zone", True, "safe"),
    "check-name": _op(("zone", "kind", "project", "thread", "name", "party", "to", "spoken", "thread_spoken"),
                      ("kind", "name", "to"), "none"),
    "rename": _op(("zone", "project", "thread", "to"), ("project", "thread", "to"), "zone", True),
    # A thread to another project of its zone (#354): `thread` is required by the handler, `to` is the project.
    "move": _op(("zone", "project", "thread", "to"), ("project", "thread", "to"), "zone", True),
    "delete": _op(("zone", "project", "thread", "confirm"), ("project", "thread"), "zone", True),
    # A project split into separate jobs (`heading`) or joined into one job (`join`, #632): `check` asks for the plan and
    # writes nothing. `thread` and `papers` stay declared so that a request that still names one is refused in words.
    "layout": _op(("zone", "project", "thread", "papers", "heading", "join", "resume_from", "check", "plan"),
                  ("project", "thread", "papers", "heading", "join", "resume_from"), "zone", True),
    "undo": _op(("zone", "commit"), ("commit",), "zone", True),
    # The settings file is in the workspace's own repository, committed with it.
    # desk-agent is the cmux extra's own setting, which its desk writes in System/desk.json.
    "settings": _op(("launchers", "default", "zones", "graph", "notifications", "memory",
                     "desk-agent", "release-notice", "release-notice-every", "ask", "channels", "usage-counts"), (), "workspace"),
    # Settings › About Garrick (#410): Check for updates asks GitHub now and writes only the kept answer; the update
    # that follows a newer release runs release.py's own, which commits in each repository it changes.
    "release-check": _op((), (), "workspace", retry="safe"),
    # `held` answers the plan's list of Garrick files with changes not committed: "commit" or "rest" (the page's buttons);
    # the paths come from a plan made on that request, never from here.
    "release-update": _op(("held",), (), "workspace", retry="safe"),
    # Settings › Memory's unsaved values, counted by fade.py (#108): it only reads.
    "memory-preview": _op(("memory",), (), "none", retry="safe"),
    # A note from Explore's card (#206): read for its Preview, which only
    # reads, or opened in the app the Mac uses for a .md file.
    "note-read": _op(("path",), ("path",), "none", retry="safe"),
    "note-open": _op(("path",), ("path",), "machine"),
    # A new session in the Claude or Codex desktop app (#652): the page names a key and a folder, the reply
    # carries the link the app opens. It only reads.
    "session-url": _op(("key", "folder"), ("key", "folder"), "none", retry="safe"),
    # A Needs you question (#175), listed in Waiting on you now, answered by one of its
    # options, or put off to a later day: the question's file and the work's
    # note, committed in its zone.
    # `text` is an answer in the user's own words, for a question whose
    # `own:` names the label that takes them (#182).
    "answer": _op(("zone", "file", "label", "text"), ("file", "label", "text"), "zone", True),
    "later": _op(("zone", "file", "until"), ("file", "until"), "zone", True),
    # A wiki question (#224): the user's words filed as a raw answer, then the
    # question changed. Neither commits (a wiki's commit is the skill's) and
    # the words are no part of what the request is. `question-decide` (point
    # 5) writes the raw answer and the decision page in one transaction.
    # `question-work` only reads.
    "question-answer": _op(("wiki", "file", "words"), ("wiki", "file"), "workspace"),
    "question-later": _op(("wiki", "file", "until"), ("wiki", "file", "until"), "workspace"),
    "question-close": _op(("wiki", "file"), ("wiki", "file"), "workspace"),
    "question-decide": _op(("wiki", "file", "words"), ("wiki", "file"), "workspace"),
    "question-work": _op(("wiki", "file"), ("wiki", "file"), "none", retry="safe"),
    "question-done": _op(("wiki", "file"), ("wiki", "file"), "workspace"),
    # Open sections as questions (#224, point 8): a read without `confirm`; with it,
    # one question file per line, committing nothing and changing no page.
    "question-open-sections": _op(("wiki", "confirm", "pages"), ("wiki", "confirm"), "workspace"),
    # Allow once: an allowance taken away. Writes System/walls-allowed.json and commits it in the workspace's own repository.
    "walls-unallow": _op(("path", "id"), ("path", "id"), "workspace", True),
    # The Context queue's wall question (#548, #550): the look only reads (the wall check run on a file or a place, the words
    # two files share in the reply and nowhere else); the allowance is `check.py allow`'s ledger entry with `by: page`, written
    # after that look, for the blob it showed. Both only from the app's bridge (page_action.py's PAGE_ONLY).
    "walls-look": _op(("place", "path", "id"), ("place", "path", "id"), "none", retry="safe"),
    "walls-allow": _op(("path", "id", "blob"), ("path", "id", "blob"), "workspace", True),
    # An answer to a finding on the Checks card's queue (#535): older entries moved to history and committed in the
    # note's zone, a preview of that, or Not now. Closed by finding_queue.py's table.
    # `commit` and `repo` ride only with Undo, which reverts the one commit a bounded edit made (#592).
    "finding": _op(("kind", "path", "answer",
                    "commit",
                    "repo",
                    "old",
                    "new"), ("kind", "path", "answer"), "workspace", True),
    # Process the Inbox in the background (#634): one run at the workspace root, started and not waited for, and the answer to a
    # question it asked, which files that one item. Both only from the app's bridge (page_action.py's PAGE_ONLY).
    "inbox-run": _op((), (), "none"),
    "intake-answer": _op(("zone", "file", "label"), ("zone", "file", "label"), "zone", True),
    # Continue commits the work's own record in its zone, then opens it in
    # Claude's desktop app; Ask something opens the app on the workspace.
    # `suggested` asks a first look's suggested request instead (#182).
    "continue": _op(("zone", "file", "suggested"), ("file", "suggested"), "zone", True),
    "ask-desktop": _op(("prompt",), (), "machine"),
    # Your own work (#182). A folder looked through by discover.py, names and
    # dates only, its proposals kept in System/generated/; a proposal answered,
    # a yes making Garrick's record of the work, committed in its zone; a
    # first look written from the work's files; the record put away under the
    # zone's archive/ and brought back. None of them writes in the folder.
    # `owner` answers whose work it is, where the work's zone has no party yet.
    "suggestion": _op(("id", "answer", "name", "zone", "party", "owner"), ("id", "answer", "name"), "zone", True),
    "start": _op(("zone", "file"), ("file",), "zone", True),
    "stop-using": _op(("zone", "file"), ("file",), "zone", True),
    "bring-back": _op(("zone", "project"), ("project",), "zone", True),
    # Where a work's files live (#189): Keep a copy, Refresh now, the media
    # switch, Move into Garrick, Undo the move, and back to left in place, the
    # copy kept or deleted; committed in its zone. Stop, while a copy or a move
    # is still copying and checking, and how far it has got, which only reads.
    # A work's own file opened, its folder shown in Finder, or an earlier
    # version opened or saved as a separate file (`to`, from the Save panel).
    "files": _op(("zone", "file", "do"), ("file", "do"), "zone", True),
    "files-stop": _op(("zone", "file"), ("file",), "workspace"),
    "files-progress": _op(("zone", "file"), ("file",), "none", retry="safe"),
    "work-file": _op(("zone", "file", "do", "path", "version", "to"), ("file", "do", "path", "version"), "machine"),
    # The example's Remove and Bring back: System/tools/example.py (#174).
    "example": _op(("do",), ("do",), "workspace"),
    # A check finding's Fix, from the Threads card (#179): nurture.py's own
    # mechanical fix for the note named, committed in its zone. It gathers
    # the findings again before it changes anything, so a second one finds
    # nothing left to fix.
    "fix": _op(("zone", "file"), ("file",), "zone", True, "safe"),
    # launchd starts the job; nothing in the workspace is touched here.
    "run": _op(("job",), ("job",), "machine"),
    # The cmux verbs: a tab in a folder, by name or by the folder itself.
    # `agent`: the assistant the tab starts, for this open only (#307).
    "open": _op(("zone", "project", "thread", "folder", "prompt", "agent"), ("project", "thread", "folder"), "machine"),
    "close": _op(("zone", "project", "thread"), ("project", "thread"), "machine"),
    # The checkpoint a session writes into a thread note as the work happens,
    # sent as one JSON object to scaffold.py. The one declared verb the page
    # cannot send: confirming a checkpoint is a wrap, and the page has no
    # source for one. `read` asks for what is in the note and writes nothing.
    "checkpoint": _op(("zone", "project", "thread", "base", "prev", "items", "drop", "read"),
                      ("project", "thread"), "zone", False, "safe", "checkpoint"),
    # *Commit them* on the Overview's row for changes not committed (#595): the listed files of one zone, committed by
    # the engine's bounded commit, or that commit taken back (`undo` with its `repo`). Only the app's bridge.
    "commit-files": _op(("zone", "files", "undo", "repo"), ("zone", "files", "undo"), "zone", True),
    # *Chase* on a Follow-ups row (#603): a Waiting on line whose chase day has come, by key. It drafts a message and, at
    # Act, queues the send through `hold`; it never sends and never writes a file. Only the app's bridge. A second one
    # for a line already held is refused by the handler.
    "chase": _op(("zone", "file", "key"), ("file", "key"), "zone", False, "safe"),
    # The one verb that only reads: the open set of records, for a page that
    # was reloaded. It carries nothing but its own name.
    "operations": _op((), (), "none", retry="safe"),
    # A request held in a zone's outbox, taken out of it unapplied (#612): only the app's bridge.
    "outbox-drop": _op(("zone", "id"), ("zone", "id"), "zone", retry="safe"),
    # Settings (#621): this computer's role, written outside the workspace; and the read guard, whose hook is registered in
    # the assistants' own settings and whose four choices are kept in the workspace's settings file. Only the app's bridge.
    "machine-role": _op(("role", "name", "server"), (), "machine", retry="safe"),
    "read-guard": _op(("mode", "cross", "tools", "skip"), (), "workspace", retry="safe"),
    # Connected services (#683): a service by its plain name, Check it or Leave it; the handler writes the patterns into the
    # read guard's two lists in the workspace's settings file. `add` is Add a service. Only the app's bridge.
    "connected-service": _op(("service", "choice", "add"), (), "workspace", retry="safe"),
    # Answers (#683): Faster, Balanced or Fuller for Ask or Telegram, kept as the channel's tier and effort. Only the app's bridge.
    "channel-answers": _op(("channel", "answers"), (), "workspace", retry="safe"),
    # The wrap (#645): the assistant's words in `input`, one JSON object, handed to System/tools/wrap.py, which does the lock,
    # the writes and the commit in the zone and answers with its receipt. A second run writes a second dated entry.
    "wrap": _op(("zone", "project", "thread", "input"), ("project", "thread"), "zone", True),
    # Which card of the App was opened (#651): one id from view.CARDS, added to that day's count in
    # System/garrick-usage.json. Only the app's bridge. It commits nothing and keeps no record here, as it is no
    # operation on the work; the settings say whether it counts at all.
    "count-card": _op(("card",), ("card",), "workspace", False, "safe"),
    # Remote access (preview): Settings' own switch, pairing code, reach and revoke, which change only at the Mac. The page
    # sends it and nothing else does (page_action.py's PAGE_ONLY); the handler is the extra's own System/remote/
    # settings_actions.py, and without the extra the verb is refused in a sentence. `action` is one of page_action.REMOTE_ACTIONS.
    "remote": _op(("action", "grant", "zone", "read", "write", "address", "adapter", "acknowledged", "request"), (), "machine", retry="safe"),
}
# The verbs that keep a durable record: what the page sends under the zone
# lock and commits a note. `OPS` is the name page_action.py has used since
# 0.26.0, and the name read() reports, so it keeps meaning exactly that.
RECORDED = ("park", "wake", "todo-done", "todo-undo", "todo-date", "todo-add", "note-add", "todo-edit", "todo-retire")
OPS: Dict[str, Op] = {verb: DECLARED[verb] for verb in RECORDED}
# A roaming machine's copy of the workspace only receives, so a Todo action made there is queued in its zone's outbox
# and applied on the server, `via: outbox` (#612). It carries these four verbs and no other, and `via_refusal` says so.
OUTBOX_VERBS = ("todo-done", "todo-undo", "todo-edit", "todo-add")
OUTBOX_ONLY = "the outbox carries only a tick, an untick, a reworded line and a new line"


def via_refusal(via, verb) -> Optional[str]:
    """Why `via` may not send this verb, or None. Only the outbox is limited: its four verbs, and nothing else."""
    if via == "outbox" and verb not in OUTBOX_VERBS:
        return OUTBOX_ONLY
    return None


# What an absent field means, so that leaving it out and sending it say the same.
DEFAULTS = {"target": "-", "date": "-"}
# For park and wake, the status the verb would set, and so the one a note
# already has nothing to do about. This is their precheck's whole content.
SETS = {"park": "parked", "wake": "active"}
FIELD_MAX = 40                  # of a field's name, in the sentence that refuses it


class BadOp(Exception):
    """The correlation id is not of the right shape."""


def mint_op() -> str:
    return secrets.token_hex(8)


def valid_op(op) -> bool:
    return isinstance(op, str) and OP_RE.fullmatch(op) is not None


def _norm(name: str, value):
    if isinstance(value, str):
        value = value.strip()
    if value is None or value == "":
        return DEFAULTS.get(name)
    return value


def lines_of(req: dict) -> List[str]:
    """The lines a Todo request names, in its order and each once: `keys`,
    a batch, or the one `key`. Empty for a request that names none."""
    keys = req.get("keys")
    named = list(keys) if isinstance(keys, list) else [keys] if keys not in (None, "") else []
    if req.get("key") not in (None, ""):
        named.append(req.get("key"))
    out: List[str] = []
    for k in named:
        k = k.strip() if isinstance(k, str) else k
        if k not in out:
            out.append(k)
    return out


def workspace_id(workspace) -> str:
    """The workspace root's resolved path, the one string that says which workspace a request is for. Empty when none
    is given: such a request matches only another that named none."""
    if not workspace:
        return ""
    try:
        return str(Path(str(workspace)).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(workspace)


def identity_key(verb: str, req: dict, workspace="") -> str:
    """sha256 of the canonical JSON of the verb, the workspace root, the zone
    and the verb's identity fields. A row journalled before 0.76.0 was hashed
    without the workspace, so it matches nothing. Field order, a missing field against a null or empty
    one, and a client's own `op` or `key`-like extras do not change it.
    The lines of a batch are one set, in whatever order they were ticked,
    and a batch of one is the request that names that line by `key`."""
    spec = OPS[verb]
    fields = {k: _norm(k, req.get(k)) for k in sorted(spec.identity)}
    if "keys" in fields:
        lines = sorted(lines_of(req), key=str)
        del fields["keys"]
        fields["key"] = lines[0] if len(lines) == 1 else (lines or None)
    body = {"verb": verb, "workspace": workspace_id(workspace), "zone": _norm("zone", req.get("zone")), "fields": fields}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# Closed validation, and the precheck --------------------------------------


def _field_name(key) -> str:
    """A field's name as a sentence may carry it: one line, cut short."""
    name = " ".join(str(key).split())
    if len(name) > FIELD_MAX:
        name = name[:FIELD_MAX] + "…"
    return name or "(nothing)"


def undeclared(verb: str, req: dict) -> List[str]:
    """The fields of the request the verb does not declare, sorted. Empty for
    a verb the table does not know: that is the caller's refusal to make."""
    spec = DECLARED.get(verb)
    if spec is None or not isinstance(req, dict):
        return []
    return sorted(k for k in req if k not in spec.fields and k not in ALWAYS)


def validate(verb: str, req: dict) -> Optional[str]:
    """Why a request is refused before anything runs, or None to carry on.

    Closed: a field the verb does not declare is refused by name, rather than
    ignored, which is what stops an unknown field widening what an action
    touches. A verb the table does not declare is not judged here; the
    caller's own list of what it does says no first."""
    extra = undeclared(verb, req)
    if not extra:
        return None
    # The negation is repeated before every name on purpose: affirms() reads
    # the words before a success verb, so a field spelled `saved` still has
    # a `no` in front of it and the refusal cannot be read as a success.
    return NO_FIELD.format(verb=verb, names=" and ".join(ONE_FIELD.format(name=_field_name(k)) for k in extra))


def stale(verb: str, req: dict, found) -> Optional[str]:
    """Why the request no longer means what it did, or None to carry on.

    `found` is the fingerprint the verb's `precheck` names, read from the
    world now: for the Todo verbs the key of the line the request still
    points at, falsy when no live line has it; for park and wake the note's
    `status:` as its frontmatter has it, "" for a note with none. Nothing
    here computes a fingerprint, so there is one hash of a Todo line in the
    workspace and one reading of a note's status, not a second of each."""
    kind = DECLARED[verb].precheck if verb in DECLARED else None
    if kind is None:
        return None
    if kind == "line":
        return None if found else STALE_WHY[("line", None)]
    if kind == "checkpoint":
        # (the Resume here block's hash now, the key of the checkpoint in the
        # note now) against the two the writer last read. Either one changed,
        # and another writer has been here since: nothing is written.
        here = tuple(found or (None, None))
        return None if here == (_norm("base", req.get("base")), _norm("prev", req.get("prev"))) \
            else STALE_WHY[("checkpoint", None)]
    if str(found or "").strip().lower() != SETS[verb]:
        return None
    return STALE_WHY[("status", verb)].format(name=name_of(verb, req))


# The words ----------------------------------------------------------------

_SUCCESS = re.compile(r"\b(%s)\b" % "|".join(SUCCESS_VERBS), re.I)
_NEGATED = re.compile(r"(?:\bnot|\bno|\bnever|\bnothing|\bwithout|\bcannot|\bnor|n't)\s+(?:[\w'-]+\s+){0,2}$", re.I)


def affirms(sentence: str) -> bool:
    """Does the sentence say a success verb in the affirmative? "Not
    committed" does not; "made, but not committed" does, by "made"."""
    text = sentence or ""
    for m in _SUCCESS.finditer(text):
        if not _NEGATED.search(text[max(0, m.start() - 28):m.start()]):
            return True
    return False


def name_of(verb: str, req: dict) -> str:
    """What the request is about, for a sentence."""
    if verb in ("park", "wake", "checkpoint"):
        for k in ("thread", "project"):
            if isinstance(req.get(k), str) and req[k].strip():
                return req[k].strip()
        if isinstance(req.get("file"), str) and req["file"].endswith(".md"):
            return Path(req["file"]).stem
        return "that note"
    return "that Todo line" if verb != "todo-add" else "the new Todo line"


WORKING = {"park": "Parking {name}…", "wake": "Waking {name}…", "todo-done": "Ticking that line…",
           "todo-undo": "Reopening that line…", "todo-date": "Changing that line's date…",
           "todo-add": "Adding to {zone}…", "note-add": "Saving the note…", "todo-edit": "Rewording that line…",
           "todo-retire": "Retiring that line…"}
ALREADY = {"park": "Already parking {name}…", "wake": "Already waking {name}…",
           "todo-done": "Already ticking that line…", "todo-undo": "Already reopening that line…",
           "todo-date": "Already changing that line's date…", "todo-add": "Already adding to {zone}…",
           "note-add": "Already saving the note…", "todo-edit": "Already rewording that line…",
           "todo-retire": "Already retiring that line…"}
# What a request is told when it repeats one the record holds, past the window:
# what was done and when, that this one did nothing, and the question. {when}
# reads "4 minutes ago, at 14:02"; {said} is the earlier action's own sentence,
# {doing} its label. Nothing here says this request was saved, because it was
# not: what it repeats was, and the sentence says so in that action's words.
AGAIN = {
    "completed": "The same request was done {when}: {said} It has not been done again. "
                 "Do you want it done a second time?",
    "running": "The same request is still running, started {when}: {doing} It has not been sent again. "
               "Do you want it done a second time once that one ends?",
}
# The sentence for each way an action ends other than saved. {what} is the
# thing the action would have changed; {zone} where to look.
SAYINGS = {
    "refused": "Not done. {why}",
    "crashed": "That did not work: {why} Check git status in {zone} before trying again.",
    "unknown": "We do not know whether {what} went through: the action stopped before it reported. "
               "Run git log -1 in {zone} to see whether the change landed. Trying again is safe: it checks first.",
    "lost": "No record of this action was found, so we do not know whether it went through. "
            "Run git log -1 in {zone}, then try again: it checks first.",
}
FALLBACK_WHY = {"refused": "A check refused it.", "crashed": "The action stopped with an error."}
# The two refusals this file makes itself, which say() then puts in its
# sentence. Validation: the field, named. The precheck: what the world says
# now, keyed by the fingerprint and the verb. Both are read by whoever sent
# the request, so the words are here rather than in each caller.
# The name comes straight after the `no` on purpose: a field spelled `saved`
# must still read as a refusal, and both guards on that read two words back.
NO_FIELD = "{verb} takes {names}"
# The rule's own words for a wall that held something back, in rules.md under
# "Zones and walls", quoted whole (#116). Any page action the zone's wall
# check refused ends on this and nothing else (#107, #172): no party, no
# person, no subject, no tag, and no refusal wording of this file's added to it.
WALL_REFUSAL = "A wall holds some material back from this project, so I have not used it. Nothing was written."
ONE_FIELD = "no {name} field"
STALE_WHY = {
    ("line", None): "that line has changed since the page was built; it rebuilds now, try again",
    ("status", "park"): "{name} was set aside already, so nothing was changed",
    ("status", "wake"): "{name} is active already, so nothing was changed",
    ("checkpoint", None): "the thread note has moved on since it was read; nothing was written. "
                          "Read the checkpoint again and write it afresh",
}


# A batch of several lines, in place of WORKING and ALREADY's "that line".
WORKING_LINES = {"todo-done": "Ticking {n} lines…", "todo-undo": "Reopening {n} lines…"}
ALREADY_LINES = {"todo-done": "Already ticking those {n} lines…", "todo-undo": "Already reopening those {n} lines…"}


def label(verb: str, req: dict, already: bool = False) -> str:
    n = len(lines_of(req)) if verb in WORKING_LINES else 0
    if n > 1:
        return (ALREADY_LINES if already else WORKING_LINES)[verb].format(n=n)
    table = ALREADY if already else WORKING
    return table[verb].format(name=name_of(verb, req), zone=req.get("zone") if isinstance(req.get("zone"), str) else "the zone")


def _when(then: float, now: float) -> str:
    """When something happened, said both ways: "4 minutes ago, at 14:02"."""
    minutes = max(1, int(round((now - then) / 60.0)))
    ago = "a minute ago" if minutes == 1 else "%d minutes ago" % minutes
    return "%s, at %s" % (ago, time.strftime("%H:%M", time.localtime(then)))


def _stop(text: str) -> str:
    text = " ".join(str(text or "").split()).rstrip("…")
    return text + ("" if not text or text[-1] in ".!?" else ".")


def asked(rec: dict, now: float) -> dict:
    """The reply to a request that repeats `rec` past the window: nothing ran,
    and the question. `again` names the action to put in `confirm` to have it
    done a second time; `ok` is false, since this request did nothing."""
    if rec.get("state") in ("queued", "running"):
        say = AGAIN["running"].format(when=_when(rec.get("at") or now, now), doing=_stop(rec.get("label") or "Working"))
    else:
        say = AGAIN["completed"].format(when=_when(rec.get("done") or rec.get("at") or now, now), said=_stop(rec.get("say") or "Done"))
    return {"ok": False, "say": say, "op": rec["op"], "state": "asked", "again": rec["op"]}


def _sentence(why: str, outcome: str) -> str:
    why = " ".join(str(why or "").split())
    if not why or affirms(why):
        return FALLBACK_WHY.get(outcome, "")
    why = why[0].upper() + why[1:]
    return why if why[-1] in ".!?" else why + "."


def say(outcome: str, verb: str, req: dict, why: str = "", said: str = "") -> str:
    """The sentence an action ends on. Only `saved` says what the handler
    said; every other outcome is built here, from its own template."""
    if outcome not in OUTCOMES:
        raise ValueError("not an outcome: %r" % (outcome,))
    if outcome == "saved":
        return said or "Done."
    if outcome == "refused" and " ".join(str(why or "").split()) == WALL_REFUSAL:
        return WALL_REFUSAL
    zone = req.get("zone") if isinstance(req.get("zone"), str) else "the zone"
    return SAYINGS[outcome].format(why=_sentence(why, outcome), what=_what(verb, req), zone=zone)


def _what(verb: str, req: dict) -> str:
    if verb == "todo-add":
        return "the new Todo line"
    if verb.startswith("todo-"):
        return "the change to those Todo lines" if len(lines_of(req)) > 1 else "the change to that Todo line"
    return "the change to " + name_of(verb, req)


def state_for(outcome: str) -> str:
    return "completed" if outcome == "saved" else "failed"


def lost_sentence() -> str:
    """The page's own sentence for an entry the journal does not know, with
    {zone} for the page to fill in."""
    return SAYINGS["lost"]


# The journal -------------------------------------------------------------


def _request(verb: str, req: dict) -> dict:
    """Only the fields the verb declares, a new line's text cut short. A note's own words are never kept: the record
    holds where it went, and the note holds what it says."""
    out = {}
    for k in OPS[verb].fields:
        if verb == "note-add" and k == "text":
            continue
        if k in req:
            v = req[k]
            if isinstance(v, str) and len(v) > LOGGED_TEXT:
                v = v[:LOGGED_TEXT] + "…"
            out[k] = v
    return out


class Journal:
    """operations.jsonl and its lock in one jobs folder."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.path = self.folder / FILE

    def usable(self) -> bool:
        """Can records be written here at all? False on a platform without
        flock, or when the folder cannot be made or written."""
        if fcntl is None:
            return False
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            os.close(os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600))
            return True
        except OSError:
            return False

    @contextlib.contextmanager
    def lock(self, wait: float = 5.0):
        """The journal's own lock, for a read that must agree with the write
        that follows it. Best effort: past `wait`, the block runs without."""
        fd = None
        try:
            fd = os.open(str(self.folder / JOURNAL_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
            deadline = time.time() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.02)
        except (OSError, AttributeError):
            pass
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)

    def append(self, rec: dict) -> None:
        """One line, in one write. A terminal record without a valid outcome
        is a programming error and is refused loudly; a file that cannot be
        written is not, and stops nothing."""
        if rec.get("state") in ("completed", "failed"):
            if rec.get("outcome") not in OUTCOMES:
                raise ValueError("a terminal record needs an outcome, got %r" % (rec.get("outcome"),))
            if (rec["state"] == "completed") != (rec["outcome"] == "saved"):
                raise ValueError("only `saved` completes: %r is %s" % (rec["outcome"], rec["state"]))
        elif rec.get("state") not in STATES:
            raise ValueError("not a state: %r" % (rec.get("state"),))
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            fd = os.open(str(self.path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            pass

    def records(self) -> List[dict]:
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out = []
        for raw in text.splitlines():
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict) and isinstance(rec.get("op"), str):
                out.append(rec)
        return out

    def latest(self) -> "collections.OrderedDict[str, dict]":
        """The last record of each op, in the order the ops began."""
        seen: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        for rec in self.records():
            seen[rec["op"]] = rec
        return seen

    def run_path(self, op: str) -> Path:
        return self.folder / ("op-%s.run" % op)

    def alive(self, op: str) -> bool:
        """Is a worker holding this op's lock? A missing file is no worker."""
        try:
            fd = os.open(str(self.run_path(op)), os.O_RDWR)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            return False
        finally:
            os.close(fd)

    def settle_dead(self, now: float) -> None:
        """Write `unknown` for each op that is not terminal and has no worker.
        Under the journal's lock, re-reading first: a worker that finished
        between the caller's read and now has already written its own."""
        for op, rec in list(self.latest().items()):
            if rec.get("state") in ("completed", "failed") or self.alive(op):
                continue
            verb, req = rec.get("verb"), rec.get("request") or {}
            req = dict(req, zone=rec.get("zone"))
            sentence = say("unknown", verb, req) if verb in OPS else SAYINGS["unknown"].format(
                what="the change", zone=rec.get("zone") or "the zone")
            self.append(dict(rec, state="failed", phase="", done=now, outcome="unknown", say=sentence))
            try:
                self.run_path(op).unlink()
            except OSError:
                pass

    def open_set(self, now: Optional[float] = None, workspace="") -> List[dict]:
        """What a page is shown: every record that is not terminal, and each
        terminal one from the last RECENT seconds, of this workspace's own: a
        record with another workspace, or none (written before 0.76.0), is
        never shown. A worker found dead is settled first."""
        now = time.time() if now is None else now
        with self.lock():
            self.settle_dead(now)
            where = workspace_id(workspace)
            latest = [r for r in self.latest().values() if r.get("workspace") == where]
        out = []
        for rec in latest:
            if rec.get("state") not in ("completed", "failed") or now - (rec.get("done") or rec.get("at") or 0) <= RECENT:
                shown = {k: rec.get(k) for k in ("op", "verb", "zone", "state", "phase", "at", "done", "outcome", "say", "label")}
                lines = lines_of(rec.get("request") or {}) if rec.get("verb") in ("todo-done", "todo-undo") else []
                if lines:               # every line of a tick or untick, so a reload knows which rows are pending
                    shown["keys"] = lines
                out.append(shown)
        return out

    def compact(self, now: float) -> None:
        """Past COMPACT_BYTES, keep each op's last record, and only the ones
        that are not terminal or ended in the last day. Under the lock."""
        try:
            if self.path.stat().st_size < COMPACT_BYTES:
                return
        except OSError:
            return
        keep = [r for r in self.latest().values()
                if r.get("state") not in ("completed", "failed") or now - (r.get("done") or r.get("at") or 0) <= KEEP]
        tmp = self.folder / (FILE + ".tmp")
        try:
            tmp.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in keep), encoding="utf-8")
            os.replace(str(tmp), str(self.path))
        except OSError:
            pass


class Run:
    """One action's journal entry, from `queued` to its terminal record."""

    def __init__(self, journal: Journal, rec: dict, fd: int):
        self.journal, self.rec, self.fd = journal, rec, fd
        self.finished = False

    @property
    def op(self) -> str:
        return self.rec["op"]

    def _write(self, **change) -> None:
        self.rec = dict(self.rec, **change)
        with self.journal.lock():
            self.journal.append(self.rec)

    def running(self) -> None:
        if not self.finished and self.rec["state"] != "running":
            self._write(state="running", phase="")

    def phase(self, text: str) -> None:
        if not self.finished:
            self._write(state="running", phase=text)

    def finish(self, outcome: str, req: dict, why: str = "", said: str = "") -> dict:
        """Write the terminal record and return the reply to hand back:
        {"ok", "say", "op", "state", "outcome"}. `ok` is true only for saved."""
        verb = self.rec["verb"]
        sentence = say(outcome, verb, req, why=why, said=said)
        state = state_for(outcome)
        self._write(state=state, phase="", done=time.time(), outcome=outcome, say=sentence)
        self.finished = True
        return {"ok": outcome == "saved", "say": sentence, "op": self.op, "state": state, "outcome": outcome}

    def close(self, req: dict) -> None:
        """Whatever happened, leave a terminal record, then let go of the lock."""
        try:
            if not self.finished:
                self.finish("crashed", req, why="the action was stopped before it finished.")
        finally:
            try:
                self.journal.run_path(self.op).unlink()
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass


def start(folder, req: dict, now: Optional[float] = None, via: str = "", workspace="") -> Tuple[Optional[Run], Optional[dict]]:
    """Begin the journal entry for a request of a declared verb. `via` names
    the caller that sent it, one of CALLERS, and goes into the record.

    Returns (run, None) to carry on, (None, reply) when the request joins an
    identical one that is under way, replays one that saved, or is asked
    whether it is meant a second time (`repeats()` says which), and (None,
    None) when nothing can be recorded here: the caller then does exactly
    what it would without this module. A request whose `confirm` names the
    action it would be asked about carries on. Raises BadOp for an op of the
    wrong shape.

    `workspace` is the workspace root the request is for. It is part of the
    request's identity, and the record keeps it: the journal is one file per
    machine account, and two workspaces on it never join or replay each
    other's action. A row with no workspace, written before 0.76.0, is never
    joined, replayed or asked about, and is left as it is."""
    now = time.time() if now is None else now
    verb = req["verb"]
    op = req.get("op")
    if op is None or op == "":
        op = mint_op()
    elif not valid_op(op):
        raise BadOp("not an operation id")
    journal = Journal(folder)
    if not journal.usable():
        return None, None
    where = workspace_id(workspace)
    key = identity_key(verb, req, where)
    zone = req.get("zone") if isinstance(req.get("zone"), str) else ""
    try:
        fd = os.open(str(journal.run_path(op)), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None, None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                         # this very op is running already
        os.close(fd)
        return None, {"ok": True, "say": label(verb, req, already=True), "op": op, "state": "running"}
    try:
        with journal.lock():
            journal.settle_dead(now)
            earlier_op = journal.latest().get(op)
            if earlier_op is not None and earlier_op.get("workspace") == where and earlier_op.get("key") != key:
                # An operation id names one request. The same id with other words is a mistake or a forgery, never a retry.
                raise BadOp("this operation id was used for another request")
            how, earlier = repeats([r for r in journal.latest().values() if r.get("workspace") == where], key, zone, op, now)
            if how == "join":
                return _release(journal, fd, op), {"ok": True, "say": label(verb, req, already=True),
                                                   "op": earlier["op"], "state": "running"}
            if how == "replay":
                return _release(journal, fd, op), {"ok": True, "say": earlier["say"], "op": earlier["op"],
                                                   "state": "completed", "outcome": "saved"}
            if how == "ask" and req.get("confirm") != earlier["op"]:
                return _release(journal, fd, op), asked(earlier, now)
            rec = {"op": op, "key": key, "workspace": where, "verb": verb, "zone": zone, "state": "queued", "phase": "", "at": now,
                   "request": _request(verb, req), "done": None, "outcome": None, "say": None,
                   "label": label(verb, req)}
            if via in CALLERS:
                rec["via"] = via
            journal.append(rec)
            journal.compact(now)
    except BaseException:
        _release(journal, fd, op)
        raise
    return Run(journal, rec, fd), None


def repeats(latest: List[dict], key: str, zone: str, op: str, now: float) -> Tuple[Optional[str], Optional[dict]]:
    """Whether a request with this identity key repeats an action the record
    holds, and what comes of it: ("join", rec) or ("replay", rec) inside
    IDEM_WINDOW, ("ask", rec) past it, or (None, None) to run.

    One still under way, the latest with this key: joined inside the window of
    its start, asked about past it for as long as it runs. One that saved: the
    latest save in this zone, if it has this key, answered with inside the
    window of its end and asked about until LOOKBACK. A different save in the
    zone since then (a wake after a park) means the same request is a new
    one. A refusal, a crash or an unknown is never remembered: trying again
    is what each of those says to do."""
    for rec in reversed(latest):
        if rec.get("key") != key or rec["op"] == op:
            continue
        if rec.get("state") in ("queued", "running"):
            return ("join" if now - (rec.get("at") or 0) <= IDEM_WINDOW else "ask"), rec
    saved = [r for r in latest if r.get("outcome") == "saved" and r.get("zone") == zone]
    if saved:
        last = max(saved, key=lambda r: r.get("done") or 0)
        age = now - (last.get("done") or 0)
        if last.get("key") == key and age <= LOOKBACK:
            return ("replay" if age <= IDEM_WINDOW else "ask"), last
    return None, None


def _release(journal: Journal, fd: int, op: str) -> None:
    try:
        journal.run_path(op).unlink()
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    return None


def read(folder, now: Optional[float] = None, workspace="") -> dict:
    """The reply to the page's `operations` request: the open set, and what the
    page needs to render it. `durable` is false when nothing can be recorded
    in this folder, which is what the page tells the user once."""
    journal = Journal(folder)
    if not journal.usable():
        return {"ok": True, "say": "Actions are not recoverable here.", "durable": False, "verbs": [], "ops": []}
    return {"ok": True, "say": "Checked what is running.", "durable": True, "verbs": sorted(OPS),
            "ops": journal.open_set(now, workspace), "lost": lost_sentence()}


# The commit record (#716) -----------------------------------------------
# See the docstring. One JSON file per operation in `<git dir>/garrick-ops/`,
# settled from the commit trailers git's own history holds.

RECORD_API = 1
RECORD_DIR = "garrick-ops"
TRAILER_OP = "Garrick-Op"
TRAILER_PAYLOAD = "Garrick-Payload"
RESULTS = ("done", "not-done", "unsure")
RECORD_STATES = ("prepared", "running", "settled")
RECORD_KEEP = 30 * 86400        # seconds: a settled and reported record is kept this long
HISTORY = 300                   # commits read when the commit the record started from is no longer in the history
NOT_FIELDS = ("confirm", "op", "verb")      # what a request carries that is not what it asks for
_GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")
RECEIPT_SAYINGS = {
    "done": "This was done already, in commit {short}.",
    "done-later": "Garrick stopped part way through this action. It did go through, in commit {short}.",
    "not-done": "Garrick stopped part way through this action. Nothing was changed, so you can do it again.",
    "unsure-commit": "Garrick stopped part way through this action and cannot tell whether it went through. "
                     "The change may be in commit {short}. Look at the history before you do it again.",
    "unsure": "Garrick stopped part way through this action and cannot tell whether it went through. "
              "Look at the history of the zone before you do it again.",
    "running": "This action is still running.",
}


def payload_hash(verb: str, req: dict) -> str:
    """sha256 of the canonical JSON of the verb, the zone and every field the verb declares (the words of a note
    included), `confirm` and the op excluded. Only the hash is ever kept. A missing field and an empty one
    are the same request, and the lines of a batch are one set."""
    spec = DECLARED[verb]
    fields = {}
    for k in sorted(spec.fields):
        if k in NOT_FIELDS or k == "zone":
            continue
        fields[k] = _norm(k, req.get(k))
    if "keys" in fields or "key" in fields and verb in ("todo-done", "todo-undo"):
        lines = sorted(lines_of(req), key=str)
        fields.pop("keys", None)
        fields["key"] = lines[0] if len(lines) == 1 else (lines or None)
    body = {"verb": verb, "zone": _norm("zone", req.get("zone")), "fields": fields}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def trailers(op: str, payload: str) -> str:
    """The second message paragraph a committing action carries."""
    return "%s: %s\n%s: %s" % (TRAILER_OP, op, TRAILER_PAYLOAD, payload)


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _GIT_VARS and not re.match(r"GIT_CONFIG_(KEY|VALUE)_\d+$", k)}


def _git(repo, *args, timeout: float = GIT_TIMEOUT):
    """(exit code, stdout) of one git command in `repo`; code None when git is missing or too slow."""
    import subprocess
    try:
        p = subprocess.run(["git", "-C", str(repo)] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True, timeout=timeout, env=_env())
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return p.returncode, p.stdout


def git_dir(repo) -> Optional[Path]:
    """The repository's own git directory (the worktree's, in a linked worktree), or None when `repo` is not the
    top of a repository git can read."""
    code, out = _git(repo, "rev-parse", "--absolute-git-dir", "--show-toplevel")
    lines = out.split("\n")
    if code != 0 or len(lines) < 2:
        return None
    try:
        if Path(lines[1].strip()).resolve() != Path(str(repo)).resolve():
            return None             # a folder inside another repository is not a repository of its own
    except OSError:
        return None
    return Path(lines[0].strip())


def head_of(repo) -> Optional[str]:
    """The commit HEAD is at: "" in a repository with no commit yet, None when git cannot say."""
    code, out = _git(repo, "rev-parse", "--verify", "-q", "HEAD")
    if code == 0:
        return out.strip()
    if code == 1:
        return ""
    return None


def _dir(repo, make: bool = False) -> Optional[Path]:
    gd = git_dir(repo)
    if gd is None:
        return None
    d = gd / RECORD_DIR
    if make:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    return d


def _seal(rec: dict) -> str:
    body = {k: rec.get(k) for k in ("op", "verb", "zone", "payload", "head")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@contextlib.contextmanager
def _locked(d: Path, name: str = ".lock", wait: float = 10.0):
    fd = None
    try:
        fd = os.open(str(d / name), os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.time() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    break
                time.sleep(0.02)
    except (OSError, AttributeError):
        pass
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


def _load(d: Path, op: str) -> Optional[dict]:
    """The record, or None when there is none. Raises BadOp for one whose seal does not match: it was changed by
    hand or forged, and nothing runs on it."""
    try:
        rec = json.loads((d / (op + ".json")).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise BadOp("the record of this operation cannot be read")
    if not isinstance(rec, dict) or rec.get("op") != op or rec.get("seal") != _seal(rec) or rec.get("state") not in RECORD_STATES:
        raise BadOp("the record of this operation does not match what it says")
    return rec


def _save(d: Path, rec: dict) -> None:
    rec = dict(rec, seal=_seal(rec))
    tmp = d / ("%s.json.%d.tmp" % (rec["op"], os.getpid()))
    tmp.write_text(json.dumps(rec, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(str(tmp), str(d / (rec["op"] + ".json")))


def _alive(d: Path, op: str) -> bool:
    """Is a worker holding this operation's run lock?"""
    try:
        fd = os.open(str(d / (op + ".run")), os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        return False
    finally:
        os.close(fd)


def _receipt(rec: dict, run: bool = False, new: bool = False) -> dict:
    result = rec.get("result")
    found = list(rec.get("found") or [])
    commit = rec.get("commit") or ""
    short = (commit or (found[0] if found else ""))[:7]
    if rec.get("state") != "settled":
        say_ = RECEIPT_SAYINGS["running"] if rec.get("state") == "running" else ""
    elif result == "done":
        say_ = RECEIPT_SAYINGS["done-later" if rec.get("by") == "next-run" else "done"].format(short=short)
    elif result == "not-done":
        say_ = RECEIPT_SAYINGS["not-done"]
    else:
        say_ = RECEIPT_SAYINGS["unsure-commit" if short else "unsure"].format(short=short)
    return {"op": rec["op"], "verb": rec.get("verb"), "zone": rec.get("zone"), "state": rec.get("state"), "result": result,
            "commit": commit, "found": found, "run": run, "new": new, "recorded": True, "say": say_,
            "payload": rec.get("payload"), "head": rec.get("head")}


def _unrecorded(op: str, verb: str, zone: str) -> dict:
    return {"op": op, "verb": verb, "zone": zone, "state": None, "result": None, "commit": "", "found": [], "run": True,
            "new": False, "recorded": False, "say": "", "payload": None, "head": None}


def _carrying(repo, op: str, since: str):
    """The commits that carry this op, as [(sha, payload)], and whether git could be read. Looks only at the
    commits made since `since`, or the latest HISTORY ones when that commit is not in the history any more."""
    spans = []
    if since:
        spans.append([since + "..HEAD"])
    spans.append(["-n", str(HISTORY), "HEAD"])
    for span in spans:
        code, out = _git(repo, "log", "--format=%H%x1f%B%x1e", *span)
        if code != 0:
            if span[0] == "-n" and head_of(repo) == "":
                return [], True      # no commit yet, so none carries the op
            continue
        found = []
        for chunk in out.split("\x1e"):
            if "\x1f" not in chunk:
                continue
            sha, body = chunk.split("\x1f", 1)
            last = body.strip().split("\n\n")[-1]
            ids = re.findall(r"^%s: ([0-9a-f]{8,32})$" % TRAILER_OP, last, re.M)
            if op in ids:
                pay = re.findall(r"^%s: ([0-9a-f]{64})$" % TRAILER_PAYLOAD, last, re.M)
                found.append((sha.strip(), pay[0] if len(pay) == 1 else ""))
        return found, True
    return [], False


def _decide(repo, rec: dict, ran_ok) -> dict:
    """The record, settled from git. Never guesses: what git cannot answer is `unsure`."""
    found, readable = _carrying(repo, rec["op"], rec.get("head") or "")
    shas = [sha for sha, _ in found]
    change = {"found": shas, "commit": "", "by_head": False}
    if not readable:
        result = "unsure"
    elif found:
        if len(found) == 1 and found[0][1] == rec["payload"]:
            result, change["commit"] = "done", found[0][0]
        else:
            result = "unsure"
    else:
        now = head_of(repo)
        if now is None:
            result = "unsure"
        elif now == (rec.get("head") or ""):
            gd = git_dir(repo)
            # A commit may be running still, in a process the dead worker left behind: git holds the index lock until it ends.
            result = "unsure" if gd is None or (gd / "index.lock").exists() else "not-done"
        elif ran_ok:
            result, change["commit"], change["by_head"] = "done", now, True
        else:
            result, change["found"] = "unsure", [now]
    return dict(rec, state="settled", result=result, settled=time.time(), **change)


def prepare(repo, verb: str, req: dict, op: str = "", via: str = "", workspace="") -> dict:
    """Write the record of an operation before its commit; see the docstring. Raises BadOp."""
    if verb not in DECLARED or not DECLARED[verb].commits:
        raise BadOp("this verb makes no commit")
    if op is None or op == "":
        op = mint_op()
    elif not valid_op(op):
        raise BadOp("not an operation id")
    zone = req.get("zone") if isinstance(req.get("zone"), str) else ""
    if fcntl is None:
        return _unrecorded(op, verb, zone)
    d = _dir(repo, make=True)
    if d is None:
        return _unrecorded(op, verb, zone)
    payload = payload_hash(verb, req)
    with _locked(d):
        rec = _load(d, op)
        if rec is not None:
            if rec["payload"] != payload or rec["verb"] != verb or rec.get("zone") != zone:
                raise BadOp("this operation id was used for another request")
            if rec["state"] == "running":
                if _alive(d, op):
                    return _receipt(rec)
                rec = _decide(repo, dict(rec, by="next-run"), None)
                rec["reported"] = False
                _save(d, rec)
            if rec["state"] == "settled":
                if rec["result"] == "done":
                    return _receipt(_verified(repo, rec))
                if rec["result"] == "unsure":
                    return _receipt(rec)
                # not done: the same operation may run again, from where the repository is now
        head = head_of(repo)
        if head is None:
            return _unrecorded(op, verb, zone)
        now = time.time()
        fresh = {"op": op, "verb": verb, "zone": zone, "payload": payload, "head": head, "state": "prepared",
                 "result": None, "commit": "", "found": [], "prepared": now, "settled": None, "via": via if via in CALLERS else "",
                 "workspace": workspace_id(workspace), "reported": False, "by": "", "api": RECORD_API}
        _save(d, fresh)
        _prune(d, now)
        return _receipt(fresh, run=True)


def _verified(repo, rec: dict) -> dict:
    """A settled `done` record whose commit git still holds with this op and payload; anything else is `unsure`."""
    found, readable = _carrying(repo, rec["op"], "")
    if readable and [sha for sha, pay in found if pay == rec["payload"]] == [rec.get("commit")]:
        return rec
    return dict(rec, result="unsure", found=[sha for sha, _ in found] or [rec.get("commit")])


def _prune(d: Path, now: float) -> None:
    try:
        names = list(d.glob("*.json"))
    except OSError:
        return
    for p in names:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("state") == "settled" and rec.get("reported") and now - (rec.get("settled") or now) > RECORD_KEEP:
                p.unlink()
                (d / (rec["op"] + ".run")).unlink()
        except (OSError, ValueError, KeyError):
            continue


def execute(repo, op: str, work):
    """Run `work(trailers)` for a prepared operation, then settle it from git. Returns (what work returned,
    receipt). `work` is not called, and its result is None, when the operation is not prepared, is running
    elsewhere, or is settled; the receipt says which. What `work` raises is raised again, after settling."""
    d = _dir(repo)
    if d is None or not valid_op(op) or fcntl is None:
        raise BadOp("no record of this operation")
    try:
        fd = os.open(str(d / (op + ".run")), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        raise BadOp("no record of this operation")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            with _locked(d):
                return None, _receipt(_load(d, op) or {"op": op, "state": "running"})
        with _locked(d):
            rec = _load(d, op)
            if rec is None:
                raise BadOp("no record of this operation")
            if rec["state"] != "prepared":
                return None, _receipt(rec)
            rec = dict(rec, state="running", started=time.time())
            _save(d, rec)
        done, err = None, None
        try:
            done = work(trailers(op, rec["payload"]))
        except BaseException as e:
            err = e
        receipt = settle(repo, op, ran_ok=err is None)
        if err is not None:
            raise err
        return done, receipt
    finally:
        try:
            (d / (op + ".run")).unlink()
        except OSError:
            pass
        os.close(fd)


def settle(repo, op: str, ran_ok=None) -> dict:
    """Settle an operation from git; see the docstring. A settled one returns as it was."""
    d = _dir(repo)
    if d is None or fcntl is None:
        raise BadOp("no record of this operation")
    with _locked(d):
        rec = _load(d, op)
        if rec is None:
            raise BadOp("no record of this operation")
        if rec["state"] == "settled":
            return _receipt(rec)
        rec = _decide(repo, dict(rec, by="run" if ran_ok is not None else "next-run"), ran_ok)
        rec["reported"] = ran_ok is not None
        _save(d, rec)
        return _receipt(rec)


def outcome(repo, op: str, mark: bool = True) -> dict:
    """What became of an operation: its receipt, settled from git first when a worker died in the middle. `new` is
    true only the first time a settlement that a later run made is read."""
    d = _dir(repo)
    if d is None or fcntl is None or not valid_op(op):
        raise BadOp("no record of this operation")
    with _locked(d):
        rec = _load(d, op)
        if rec is None:
            raise BadOp("no record of this operation")
        if rec["state"] == "running" and not _alive(d, op):
            rec = _decide(repo, dict(rec, by="next-run"), None)
            rec["reported"] = False
        if rec["state"] == "prepared" or (rec["state"] == "running"):
            return _receipt(rec)
        new = not rec.get("reported")
        if new and mark:
            rec["reported"] = True
            _save(d, rec)
        elif rec["state"] == "settled" and rec.get("result") == "done":
            rec = _verified(repo, rec)
        return _receipt(rec, new=new)


def sweep(repo) -> List[dict]:
    """Settle every operation in `repo` that a worker left `running` and died, and return the receipts not reported before."""
    d = _dir(repo)
    if d is None or fcntl is None or not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        op = p.name[:-5]
        if not valid_op(op):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("state") == "settled" and rec.get("reported"):
            continue
        if rec.get("state") == "prepared":
            continue                    # prepared and not started: nothing ran, and the caller may still run it
        try:
            got = outcome(repo, op)
        except BadOp:
            continue
        if got.get("new"):
            out.append(got)
    return out
