#!/usr/bin/env python3
"""finding_queue.py: the Checks card's queue (#535), one finding at a time, as a plain question with answer buttons.

status.py builds the queue at page build, for every scope, from the one-pass forecast (the latest Nurture record's
standing findings), so the number on a scope's line on the card and the number in its queue are one list's. A kind
with plain wording says one short sentence and one line on why it matters, with no path, setting name or command in
either; those stay in *Details*, closed. Every other kind shows the check's own text under a plain label, with
*Something else* as its only answer. PLAIN_KINDS lists the kinds that have plain wording, and a test holds the list,
so a new kind cannot get one silently.

Each answer names the action it takes, from the fixed table in ANSWERS:

    handoff   the finding goes to the assistant at the workspace root, by the route Process the Inbox takes
              (data-request); the page writes nothing. A wall finding's request names the file and the two zones,
              never the repeated words.
    run       a tool the workspace already has: history.py applies, check.py --install-hooks. Through the page's
              verb `finding` (page_action.py), so the commit and its wall check are the page's own.
    preview   what a run would do, said as counts, the full output under Details; nothing is written.
    open      the file, or both files of a wall finding, opened in the note app by the page's own note-open; nothing
              is written.
    later     Not now: the finding is hidden for LATER_DAYS days in System/generated/status-later.json, a page-owned
              file that holds a key for each finding and the day it comes back, never a path or any text. No check
              and no Nurture record reads it, so what the checks report is the same with and without it.

A wall finding has no Not now, and no answer that keeps the material: the recommended answer is to take it out.

This module only decides and says; it writes nothing but the Not now file, which page_action.py asks it to.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LATER_DAYS = 7
LATER_FILE = ("System", "generated", "status-later.json")
HISTORY_TOOL = ("System", "tools", "history.py")

# The kinds with plain wording, in the order a queue asks them (a wall first, always), then the mechanical kinds,
# which are never asked one by one: the card groups them under Fix them.
PLAIN_KINDS = ("wall", "note-long", "resume-long", "todo-long", "meeting-long", "hooks-missing")
MECHANICAL = "mechanical"
FREE = "Something else: tell Garrick what to do"
NO_FREE_FOR = ()          # every question keeps the free-text field, last


def A(id_: str, label: str, does: str, action: str) -> dict:
    return {"id": id_, "label": label, "does": does, "action": action}


# kind -> (tag, why, answers); the first answer is the recommended one.
ANSWERS: Dict[str, List[dict]] = {
    "wall": [A("take-out", "Take it out", "Your assistant removes it and shows you the change.", "handoff"),
             A("show-both", "Show me both texts", "Opens them in your notes app. Nothing changes.", "open")],
    "note-long": [A("move-older", "Move older entries to history", "Nothing is deleted.", "run"),
                  A("preview", "Show me what would move", "A preview. No change until you say so.", "preview"),
                  A("later", "Not now", "Ask again in a week.", "later")],
    "resume-long": [A("shorten", "Shorten it", "Your assistant writes a shorter one for you to approve.", "handoff"),
                    A("later", "Not now", "Ask again in a week.", "later")],
    "todo-long": [A("shorten", "Shorten the line", "Your assistant shortens it and moves what came of it to the thread's notes.", "handoff"),
                  A("later", "Not now", "Ask again in a week.", "later")],
    "meeting-long": [A("shorten", "Shorten it", "Your assistant shortens the page. The recording's transcript stays as it is.", "handoff"),
                     A("open", "Let me open it", "Opens the page in your notes app. Nothing changes.", "open"),
                     A("later", "Not now", "Ask again in a week.", "later")],
    "hooks-missing": [A("install", "Install the wall check", "Adds it to every repository that lacks it.", "run"),
                      A("later", "Not now", "Ask again in a week.", "later")],
}
TAGS = {"wall": "Private material", "note-long": "Tidy up", "resume-long": "Tidy up", "todo-long": "Tidy up",
        "meeting-long": "Tidy up", "hooks-missing": "Safety check"}
WHY = {"note-long": "Long pages are slow to read and slow for the assistant. Older entries can move to a history page, where they stay linked.",
       "resume-long": "A resume point is what you read first when you come back, so a short one is quicker to take in.",
       "todo-long": "A line names one action. What came of it belongs in the thread's notes.",
       "meeting-long": "A meeting note is a short record: who was there, the key points, the actions.",
       "hooks-missing": "Without it, a commit can carry private material across a wall and nothing warns you."}
ACTIONS = ("handoff", "run", "preview", "open", "later")
# The answers the verb `finding` takes (page_action.py), by kind: closed, so an unknown kind or answer is refused.
VERB_ANSWERS = {kind: tuple(a["id"] for a in answers if a["action"] in ("run", "preview", "later")) for kind, answers in ANSWERS.items()}

NOTE_RE = re.compile(r"has (\d+) words, over the \d+ of `note-max-words`")
RESUME_RE = re.compile(r"Resume here block has (\d+) words, over the \d+ of `resume-max-words`")
MEETING_RE = re.compile(r"body is (\d+) words, over the \d+ of `meeting-max-words`")
TODO_RE = re.compile(r"(\d+) lines? (?:is|are) longer than \d+ characters")
WALL_OTHER_RE = re.compile(r"points into the (.+?) zone, a walled zone")
NOTE_PATH_RE = re.compile(r"(?:Zones|Wikis)/[^\s;,`'\"()\[\]]+?\.md")


def plain_kind(item: dict) -> str:
    """The plain kind of a standing finding, from Nurture's kind and the check's name and text; "" for a kind with no
    plain wording, "mechanical" for one the nightly run fixes."""
    kind, check, line = str(item.get("kind") or ""), str(item.get("check") or ""), str(item.get("message") or item.get("line") or "")
    if kind == "wall":
        return "wall"
    if kind == MECHANICAL:
        return MECHANICAL
    if kind != "judgment":
        return ""
    if check in ("projects", "threads") and "`note-max-words`" in line and NOTE_RE.search(line):
        return "note-long"
    if check == "resume" and RESUME_RE.search(line):
        return "resume-long"
    if check == "todo" and TODO_RE.search(line):
        return "todo-long"
    if check == "meetings" and MEETING_RE.search(line):
        return "meeting-long"
    if check in ("zones", "hooks") and "no pre-commit wall check" in line:
        return "hooks-missing"
    return ""


def about(n: int) -> str:
    """A figure for the ear: to the nearest hundred, to the nearest thousand from ten thousand."""
    step = 1000 if n >= 10000 else 100
    return "about {:,}".format(int(round(n / step) * step))


def later_key(kind: str, path: str) -> str:
    """A finding's key in the Not now file: a hash of its plain kind and its path, so the file holds no path and no
    text of any zone."""
    return hashlib.sha1(("%s\0%s" % (kind, path)).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def later_path(ws) -> Path:
    return Path(ws).joinpath(*LATER_FILE)


def later_hidden(ws, today: Optional[dt.date] = None) -> set:
    """The keys put off and not yet back. A file that is missing, unreadable or of another shape hides nothing."""
    today = today or dt.date.today()
    try:
        data = json.loads(later_path(ws).read_text(encoding="utf-8"))
        rows = data["later"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    out = set()
    if isinstance(rows, dict):
        for key, until in rows.items():
            try:
                if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{16}", key) and dt.date.fromisoformat(str(until)) > today:
                    out.add(key)
            except ValueError:
                continue
    return out


def later_put(ws, key: str, today: Optional[dt.date] = None) -> str:
    """Hide a finding for LATER_DAYS days; the day it comes back, ISO. Entries already back are dropped as it
    writes. The one write this module makes, in a file of its own that nothing but the page reads."""
    today = today or dt.date.today()
    until = (today + dt.timedelta(days=LATER_DAYS)).isoformat()
    path = later_path(ws)
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("later") or {}
    except (OSError, ValueError, AttributeError):
        rows = {}
    rows = {k: v for k, v in rows.items() if isinstance(k, str) and isinstance(v, str) and v > today.isoformat()} if isinstance(rows, dict) else {}
    rows[key] = until
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "later": rows}, f, sort_keys=True)
        os.replace(tmp, str(path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return until


# ---- saying a finding -------------------------------------------------------------------------------------------

def place(path: str) -> str:
    """A zone, a wiki or System as a sentence says it."""
    parts = path.split("/")
    if parts[0] == "Zones" and len(parts) > 1:
        return parts[1]
    if parts[0] == "Wikis" and len(parts) > 1:
        return "the %s wiki" % parts[1]
    return "System"


def stem(path: str) -> str:
    return re.sub(r"\.md$", "", path.rsplit("/", 1)[-1])


def note_name(path: str) -> Tuple[str, bool]:
    """(the project's or the thread's name, whether it is a thread) for a hub or a thread note's path."""
    parts = path.split("/")
    return stem(path), "Threads" in parts


def wall_other(item: dict) -> str:
    m = WALL_OTHER_RE.search(str(item.get("line") or ""))
    return m.group(1) if m else ""


def said(plain: str, item: dict) -> Tuple[str, str]:
    """(the sentence, the line on why) for a plain kind, with the figures from the finding. No path, setting name or
    command in either."""
    path, text = str(item["path"]), str(item.get("message") or item.get("line") or "")
    if plain == "wall":
        other = wall_other(item) or "another zone"
        here = place(path)
        return ("“%s” in %s points into private material from %s." % (stem(path), here, other),
                "%s stays out of %s. Take it out before anyone else sees the file." % (other[:1].upper() + other[1:], here))
    if plain == "note-long":
        name, thread = note_name(path)
        n = int(NOTE_RE.search(text).group(1))
        return ("The %s %s is getting long: %s words." % (name, "thread note" if thread else "project page", about(n)), WHY[plain])
    if plain == "resume-long":
        name, _ = note_name(path)
        n = int(RESUME_RE.search(text).group(1))
        return ("The resume point of %s is getting long: %s words." % (name, about(n)), WHY[plain])
    if plain == "todo-long":
        n = int(TODO_RE.search(text).group(1))
        return ("%s in the %s to-do list %s longer than an action should be." % (
            "One line" if n == 1 else "%d lines" % n, place(path), "is" if n == 1 else "are"), WHY[plain])
    if plain == "meeting-long":
        n = int(MEETING_RE.search(text).group(1))
        return ("A meeting note is longer than usual: %s words." % about(n), WHY[plain])
    if plain == "hooks-missing":
        where = place(path)
        return ("%s does not check the walls before a commit." % ("The %s zone" % where if path.startswith("Zones/") else where[:1].upper() + where[1:]),
                WHY[plain])
    raise KeyError(plain)


def handoff_phrase(plain: str, answer: str, item: dict) -> str:
    """The request an answer that needs judgment hands to the assistant. It carries the finding's kind, its path and
    its zones, and never the check's wording: a wall finding's request names the file and the two zones and nothing
    the check repeated."""
    path = str(item["path"])
    if plain == "wall":
        other = wall_other(item) or "another zone"
        return ("Take the private material from %s out of %s. The file is in %s, which is walled from it. "
                "Show me the change before anything is committed." % (other, path, place(path)))
    if plain == "resume-long":
        return "Shorten the Resume here block of %s so it fits its word limit. Show me the shorter one and change nothing until I say yes." % path
    if plain == "todo-long":
        return ("Shorten the long lines of %s to one action each, and move what came of each into its thread's dated entry. "
                "Show me the change before anything is committed." % path)
    if plain == "meeting-long":
        return ("Shorten the meeting page %s to who was there, the key points and the actions. Leave the transcript as it is. "
                "Show me the change before anything is committed." % path)
    raise KeyError(plain)


def free_prefix(plain: str, item: dict) -> str:
    """What goes before the user's own words when the free-text answer is sent: the kind, the path and the zones."""
    path = str(item["path"])
    label = {"wall": "a private-material finding", "note-long": "a note that is too long", "resume-long": "a resume point that is too long",
             "todo-long": "a to-do line that is too long", "meeting-long": "a meeting page that is too long",
             "hooks-missing": "missing commit hooks"}.get(plain, "a check finding")
    if plain == "wall":
        return "About %s in %s (%s, from %s): " % (path, place(path), label, wall_other(item) or "another zone")
    return "About %s (%s): " % (path, label)


def other_files(item: dict) -> List[str]:
    """The files a wall finding names in the other zone, from the check's text, for Show me both texts."""
    other = wall_other(item)
    text = str(item.get("message") or "")
    found = []
    for p in NOTE_PATH_RE.findall(text):
        if p != item["path"] and (not other or p.startswith("Zones/%s/" % other)) and p not in found:
            found.append(p)
    return found[:1]


def question(item: dict, scope: str) -> dict:
    """One finding as a question. `item` holds kind (Nurture's), path, line and check from the record, and message,
    the quick check's own text, where the card has it."""
    plain = plain_kind(item)
    path = str(item["path"])
    details = str(item.get("message") or item.get("line") or "")
    if plain == "wall" and not item.get("listed"):
        return unlisted_wall(item, scope)
    q = {"id": plain or "other", "scope": scope, "path": path, "key": later_key(plain or "other", path), "details": details,
         "recommended": ""}
    if plain not in PLAIN_KINDS:
        q.update(tag=str(item.get("title") or "Check finding"), sentence=re.sub(r"^%s: " % re.escape(path), "", details), why="", answers=[],
                 free=free_prefix("", item))
        return q
    sentence, why = said(plain, item)
    answers = []
    for a in ANSWERS[plain]:
        a = dict(a)
        if a["action"] == "handoff":
            a["phrase"] = handoff_phrase(plain, a["id"], item)
        elif a["action"] == "open":
            a["reqs"] = [{"verb": "note-open", "path": path}]
            if plain == "wall":
                other = other_files(item)
                if other:
                    a["reqs"].append({"verb": "note-open", "path": other[0]})
                else:
                    a["label"], a["does"] = "Show me the file", "Opens it in your notes app. Nothing changes."
        else:
            a["req"] = {"verb": "finding", "kind": plain, "path": path, "answer": a["id"]}
        answers.append(a)
    q.update(tag=TAGS[plain], sentence=sentence, why=why, answers=answers, free=free_prefix(plain, item), recommended=answers[0]["id"])
    return q


def unlisted_wall(item: dict, scope: str) -> dict:
    """A wall finding that the last Nurture run holds and this page's quick check does not list. The page showed only
    a count of these (#525), never the file or the other zone, so the question names neither: it says where the
    finding is, and the one answer hands Nurture's request for that scope to the assistant, as the Nurture button did.
    Nothing is opened, since there is no file to name."""
    place_ = place(str(item["path"]))
    ask = str(item.get("ask") or "nurture the context")
    return {"id": "wall", "scope": scope, "path": "", "key": later_key("wall", str(item["path"])),
            "tag": TAGS["wall"], "sentence": "A file in %s points into private material from another zone." % place_,
            "why": "Another zone stays out of %s. The last Nurture run found it; this page's quick check does not list it." % place_,
            "details": "From the last Nurture run. It is a count here, not a file, until the check that found it is run.",
            "answers": [dict(A("take-out", "Take it out", "Your assistant goes through the wall findings of this place with you.", "handoff"), phrase=ask)],
            "free": "About a private-material finding in %s: " % place_, "recommended": "take-out"}


def forecast_questions(items: List[dict], hidden: set) -> Dict[str, List[dict]]:
    """The queue of each scope, from the forecast's findings: the list the scope's line on the card counts, less
    what Not now has put off (a wall finding is never put off, whatever a file says). The mechanical ones are not
    asked: the card fixes them together."""
    out: Dict[str, List[dict]] = {}
    for item in items:
        plain = plain_kind(item)
        if plain == MECHANICAL:
            continue
        if plain != "wall" and plain in PLAIN_KINDS and later_key(plain, str(item["path"])) in hidden:
            continue
        out.setdefault(str(item["scope"]), []).append(question(item, str(item["scope"])))
    rank = {k: i for i, k in enumerate(PLAIN_KINDS)}
    for qs in out.values():
        qs.sort(key=lambda q: (rank.get(q["id"], len(rank)), q["path"]))
    return out


# ---- the page ------------------------------------------------------------------------------------------------------

def E(s) -> str:
    return html.escape(str(s), quote=True)


def question_html(q: dict) -> str:
    rec = q["recommended"]
    opts = ""
    for i, a in enumerate(q["answers"], 1):
        data = {"a": a["action"], "id": a["id"]}
        if a["action"] == "handoff":
            data["phrase"] = a["phrase"]
        elif a["action"] == "open":
            data["reqs"] = a["reqs"]
        else:
            data["req"] = a["req"]
        hosted = a["action"] != "handoff"
        opts += ('<button class="opt%s%s" type="button" data-fa="%s"><span class="n">%d</span><span>%s<small>%s%s</small></span></button>'
                 % (" rec" if a["id"] == rec else "", " tacts" if hosted else "", E(json.dumps(data, sort_keys=True)), i, E(a["label"]),
                    '<b class="recd">Recommended.</b> ' if a["id"] == rec else "", E(a["does"])))
    opts += ('<label class="opt other"><span class="n">%d</span><input type="text" maxlength="500" autocomplete="off" '
             'data-free="%s" placeholder="%s" aria-label="%s"></label>' % (len(q["answers"]) + 1, E(q["free"]), E(FREE), E(FREE)))
    return ('<div class="q" data-q data-key="%s" data-kind="%s" data-path="%s" hidden><span class="tag%s">%s</span><p class="qs">%s</p>%s'
            '<div class="opts">%s</div><p class="hint qsay" role="status"></p>'
            '<details class="qdet"><summary>Details</summary><code>%s</code><pre class="qout" hidden></pre></details></div>'
            % (q["key"], E(q["id"]), E(q["path"]), " private" if q["id"] == "wall" else "", E(q["tag"]), E(q["sentence"]),
               '<div class="why">%s</div>' % E(q["why"]) if q["why"] else "", opts, E(q["details"])))


def dialog(root: str, queues: Dict[str, List[dict]], names: Dict[str, str]) -> str:
    """The queue's dialog: every scope's questions, hidden until the card's line opens that scope."""
    if not queues:
        return ""
    body = ""
    for scope, qs in queues.items():
        body += ('<section class="qscope" data-scope="%s" data-name="%s" hidden><div class="prog"><span>%s</span><div class="bar"><i></i></div>'
                 '<span class="qn"></span></div>%s</section>' % (E(scope), E(names.get(scope, scope)), E(names.get(scope, scope)),
                                                                  "".join(question_html(q) for q in qs)))
    body += ('<section class="qdone" hidden><div class="done"><b></b><span class="qsum"></span><div class="qnext">'
             '<button class="act primary" type="button" data-qnext hidden></button> '
             '<button class="act" type="button" data-qclose>Back to the overview</button></div></div></section>')
    return ('<dialog id="queue" class="findings queue" aria-labelledby="queue-h" data-folder="%s"><div class="fhead"><h3 id="queue-h">Findings</h3>'
            '<button class="act" type="button" data-qclose>Close</button></div><div id="qbody">%s</div></dialog>' % (E(root), body))


def fix_block(fixes: List[Tuple[str, str]], root: str) -> str:
    """The card's line for the small things Garrick fixes on its own: how many, and one button that runs `fix` for
    each note, in the app (the same fix as the Fix on a finding's own row). A browser has no way to run a fix, so
    there the button hands the request to the assistant. `fixes` are the (zone, note) of each finding the list
    offers a Fix for, so the number counts only what `fix` can do."""
    if not fixes:
        return ""
    n = len(fixes)
    requests = [{"verb": "fix", "zone": z, "file": f} for z, f in sorted(set(fixes))]       # one fix a note: it fixes every finding of the note
    return ('<div class="auto"><span>Garrick can fix %d small thing%s on its own.</span>'
            '<button class="act primary tacts" type="button" data-fix="%s">Fix them</button>'
            '<button class="act webonly" type="button" data-request="nurture the context" data-folder="%s" '
            'title="Hand “nurture the context” to your assistant">Fix them</button></div>'
            % (n, "" if n == 1 else "s", E(json.dumps(requests, sort_keys=True)), E(root)))


QUEUE_CSS = r"""
/* The queue: one finding at a time, in the page's own tokens */
dialog.queue{width:min(620px,calc(100vw - 32px))}
.queue .prog{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:13px;margin:0 0 12px}
.queue .bar{height:4px;background:var(--line);border-radius:4px;flex:1;margin:0 12px}.queue .bar i{display:block;height:100%;width:0;background:var(--accent);border-radius:4px}
.queue .q{padding:4px 0}.queue .tag{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.queue .tag.private{color:var(--critical)}.queue .qs{margin:0 0 4px;font-weight:600}.queue .why{color:var(--muted);font-size:13.5px;margin:0 0 12px}
.queue .opts{display:flex;flex-direction:column;gap:7px}
.queue .opt{display:flex;gap:10px;align-items:flex-start;text-align:left;padding:10px 12px;border-radius:10px;width:100%;font:inherit;font-size:13.5px;color:var(--ink);background:var(--surface);border:1px solid var(--line);cursor:pointer}
.queue .opt .n{flex:none;width:22px;height:22px;border-radius:6px;background:var(--raise);color:var(--muted);font-size:12px;display:grid;place-items:center;font-weight:600}
.queue .opt small{display:block;color:var(--muted);font-size:12.5px}.queue .opt.rec{border-color:var(--accent);background:var(--wash)}
.queue .opt.rec .n{background:var(--accent);color:#fff}.queue .recd{font-weight:600;color:var(--ink2)}
.queue .opt.other{cursor:text}.queue .opt.other input{flex:1;border:0;background:transparent;color:var(--ink);font:inherit;outline:none}
.queue .opt:focus-visible,.queue .opt.other:focus-within{outline:2px solid var(--accent);outline-offset:1px}
.queue .qsay{margin:8px 0 0}.queue .qsay.bad{color:var(--critical)}.queue .qdet{margin-top:10px;font-size:13px;color:var(--muted)}
.queue .qdet code,.queue .qdet pre{display:block;white-space:pre-wrap;margin:6px 0 0;font-size:12px;background:var(--raise);padding:8px;border-radius:6px}
.queue .done{text-align:center;padding:24px 8px}.queue .done b{display:block;font-size:17px;margin-bottom:4px}.queue .qnext{margin-top:14px}
.queue .q[hidden],.queue .qscope[hidden],.queue .qdone[hidden]{display:none}
.auto{display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--wash);border-radius:10px;padding:10px 12px;margin:10px 0 0;font-size:13.5px}
"""

QUEUE_JS = r"""
(function(){var dlg=document.getElementById('queue');
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
var KEY='garrick-queue',st={get:function(k){try{return sessionStorage.getItem(k)}catch(e){return null}},set:function(k,x){try{sessionStorage.setItem(k,x)}catch(e){}},del:function(k){try{sessionStorage.removeItem(k)}catch(e){}}};
function say(t){var s=document.getElementById('toast');if(s){s.textContent=t;s.classList.add('on');setTimeout(function(){s.classList.remove('on')},3500)}}
/* The Fix them button: the same fix as each finding's own Fix, one request for each, in the app */
document.addEventListener('click',function(e){var t=e.target&&e.target.closest?e.target.closest('button[data-fix]'):null;if(!t||!host)return;
var list=[];try{list=JSON.parse(t.dataset.fix)}catch(err){return}
list.forEach(function(q){host.postMessage({act:q})});say('Fixing '+list.length+' small thing'+(list.length===1?'':'s')+'…');t.disabled=true});
if(!dlg)return;
var tally={done:0,handed:0,opened:0,later:0},notes={},gone={},pend=null,cur=null;
function all(){return[].slice.call(dlg.querySelectorAll('.qscope'))}
function qs(s){return[].slice.call(s.querySelectorAll('[data-q]'))}
function pending(s){return qs(s).filter(function(q){return!gone[q.dataset.key]})}
function save(){if(cur)st.set(KEY,JSON.stringify({scope:cur.dataset.scope,gone:gone,tally:tally,notes:notes,pend:pend,t:Date.now()}))}
function sum(){var p=[];if(tally.done)p.push(tally.done+' done');if(tally.handed)p.push(tally.handed+' handed to your assistant');
if(tally.opened)p.push(tally.opened+' opened');if(tally.later)p.push(tally.later+' put off to next week');return p.join(', ')||'Nothing answered.'}
function next(){var o=all().filter(function(s){return s!==cur&&pending(s).length});return o[0]||null}
function out(q,text,bad,detail){var s=q.querySelector('.qsay');s.textContent=text||'';s.classList.toggle('bad',!!bad);
var p=q.querySelector('.qout');if(detail){p.textContent=detail;p.hidden=false}else p.hidden=true}
function show(){if(!cur)return;var every=qs(cur),left=pending(cur),n=every.length;every.forEach(function(q){q.hidden=true});
var done=dlg.querySelector('.qdone');
if(!left.length){cur.hidden=true;done.hidden=false;done.querySelector('b').textContent=cur.dataset.name+' is done.';
done.querySelector('.qsum').textContent=sum();var nx=next(),b=done.querySelector('[data-qnext]');b.hidden=!nx;
if(nx){b.textContent='Go on to '+nx.dataset.name;b.dataset.qnext=nx.dataset.scope}st.del(KEY);return}
done.hidden=true;cur.hidden=false;var k=n-left.length+1,q=left[0];q.hidden=false;
cur.querySelector('.qn').textContent=k+' of '+n;cur.querySelector('.bar i').style.width=(k/n*100)+'%';
var m=notes[q.dataset.key];if(m)out(q,m.say,m.bad,m.detail);save()}
function open(scope){var s=all().filter(function(x){return x.dataset.scope===scope})[0];if(!s)return;all().forEach(function(x){x.hidden=true});
cur=s;tally={done:0,handed:0,opened:0,later:0};gone={};notes={};pend=null;if(!dlg.open)dlg.showModal();show()}
/* The app rebuilds the page after an answer that changed something and reloads it: the queue comes back where it was, and an
   answer sent just before the reload is counted from what the new page shows */
function restore(){var r=null;try{r=JSON.parse(st.get(KEY)||'null')}catch(e){}if(!r||!r.scope||Date.now()-r.t>9e5){st.del(KEY);return}
var s=all().filter(function(x){return x.dataset.scope===r.scope})[0];if(!s){st.del(KEY);return}
cur=s;gone=r.gone||{};tally=r.tally||tally;notes=r.notes||{};pend=null;
if(r.pend&&r.pend.key){var here=qs(s).some(function(q){return q.dataset.key===r.pend.key});
if(!here){gone[r.pend.key]=1;tally[r.pend.id==='later'?'later':'done']++}
else notes[r.pend.key]={say:'It is still open. The change was not made, or was refused.',bad:true}}
dlg.showModal();show()}
function finish(q,kind){gone[q.dataset.key]=1;tally[kind]++;pend=null;show()}
function handoff(phrase){var b=document.createElement('button');b.type='button';b.setAttribute('data-request',phrase);
b.setAttribute('data-folder',dlg.dataset.folder||'');b.hidden=true;dlg.appendChild(b);b.click();b.remove()}
document.addEventListener('click',function(e){var t=e.target&&e.target.closest?e.target:null;if(!t)return;
var o=t.closest('[data-qopen]');if(o){e.preventDefault();open(o.dataset.qopen);return}
if(t.closest('[data-qclose]')){st.del(KEY);if(dlg.open)dlg.close();return}
var nx=t.closest('[data-qnext]');if(nx&&nx.dataset.qnext){tally={done:0,handed:0,opened:0,later:0};cur=all().filter(function(x){return x.dataset.scope===nx.dataset.qnext})[0];gone={};notes={};pend=null;show();return}
var b=t.closest('#queue button[data-fa]');if(!b)return;var q=b.closest('[data-q]'),d;try{d=JSON.parse(b.dataset.fa)}catch(err){return}
if(d.a==='handoff'){handoff(d.phrase);finish(q,'handed');return}
if(!host)return;
if(d.a==='open'){d.reqs.forEach(function(r){host.postMessage({act:r})});finish(q,'opened');return}
pend={key:q.dataset.key,id:d.id};save();host.postMessage({act:d.req})});
/* keys: 1 to 4 answer, the last number is the free-text field, Return takes the recommended one, Esc closes (the dialog's own) */
dlg.addEventListener('keydown',function(e){if(e.metaKey||e.ctrlKey||e.altKey)return;var q=cur&&pending(cur)[0];if(!q||q.hidden)return;
var typing=e.target&&e.target.tagName==='INPUT';
if(typing){if(e.key==='Enter'){var w=e.target.value.trim();if(w){e.preventDefault();handoff(e.target.dataset.free+w);finish(q,'handed')}}return}
if(e.key==='Enter'){var r=q.querySelector('.opt.rec');if(r&&!(e.target.closest&&e.target.closest('button'))){e.preventDefault();r.click()}return}
if(/^[1-4]$/.test(e.key)){var opts=q.querySelectorAll('.opt'),o=opts[+e.key-1];if(!o)return;e.preventDefault();
if(o.classList.contains('other')){o.querySelector('input').focus()}else o.click()}});
dlg.addEventListener('close',function(){st.del(KEY)});
var prev=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&q.verb==='finding'&&cur){var el=qs(cur).filter(function(x){return x.dataset.kind===q.kind&&x.dataset.path===q.path})[0],p=pend;pend=null;
if(el){if(res&&res.ok){if(q.answer==='preview'){notes[el.dataset.key]={say:res.say,detail:res.detail||'',bad:false};out(el,res.say,false,res.detail);save()}
else if(q.answer==='later')finish(el,'later');else finish(el,'done')}
else{notes[el.dataset.key]={say:(res&&res.say)||'That did not work.',detail:'',bad:true};out(el,(res&&res.say)||'That did not work.',true);save()}}}
if(prev)return prev(q,res)};
restore()})();
"""
