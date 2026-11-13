#!/usr/bin/env python3
"""questions_panel.py: what the Context card may ask (#224, #542).

status.py builds the page; this file, beside it, decides what the wikis' questions may show, placed by the walls, and
finding_queue.py asks them one at a time. It reads the wikis' open questions (a file each in `Wikis/<Wiki>/questions/`),
their proposed verdicts and the decisions flagged to review, one zone at a time, and the user's allowances; it calls no
model, and the answers go through page_action.py.

The walls decide what is listed. Every item is placed in a bucket, a zone, by page_action.py's View.ok(zone), the one test
a save is held to as well: a question whose zone cannot be read, or that is not in the zone shown, is placed nowhere, and
so is never listed and never counted. A page with a wall finding has no question of its own. The page is one static file,
as status.py's always is: every zone's bucket is in the page source, and a bucket holds only what is on the near side of
its own view. Nothing here adds two zones.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import importlib.util
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
WIKIS = ("Meetings", "Knowledge")
OPEN_STATES = ("open", "later")
WHY_MAX = 600
TITLE_MAX = 300
LINE_MAX = 200
VERDICTS = ("done", "stale", "duplicate")
_PA = None


def page_action():
    """page_action.py, beside this file: the walls' View and the wiki
    question reader are its, so the panel and a save are held to one test."""
    global _PA
    if _PA is None:
        spec = importlib.util.spec_from_file_location("garrick_questions_page_action", str(HERE / "page_action.py"))
        _PA = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PA)
    return _PA


def day(value) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def question_files(ws: Path, wiki: str) -> List[str]:
    """Each question file of a wiki, as a path from the wiki's folder, at any
    depth of questions/, oldest name first. A link, a hidden or archived
    folder is passed over."""
    pa = page_action()
    base = (Path(ws) / "Wikis" / wiki / pa.WIKI_QUESTION_DIR)
    out = []
    if not base.is_dir() or base.is_symlink():
        return out
    for p in sorted(base.rglob("*.md")):
        parts = p.relative_to(base).parts
        if p.is_symlink() or not p.is_file() or pa.SKIP & set(parts) or any(x.startswith((".", "_")) for x in parts):
            continue
        out.append(p.relative_to(base.parent).as_posix())
    return out


def body_parts(text: str) -> dict:
    """The bold line is the question; the prose after it, up to the first
    option or heading, is why it matters."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    ask, why = "", []
    for line in body.splitlines():
        if not ask:
            m = re.match(r"^\s*\*\*(.+)\*\*\s*$", line)
            if m:
                ask = m.group(1).strip()
        elif line.startswith("#") or re.match(r"^\s*-\s+\[", line):
            break
        elif line.strip():
            why.append(line.strip())
    return {"ask": clip(ask, TITLE_MAX), "why": clip(" ".join(why), WHY_MAX)}


def read_question(ws: Path, wiki: str, rel: str, today: dt.date, link: Callable) -> Optional[dict]:
    """One question as the panel shows it, or None. None for anything the
    walls cannot read: a question with no zone the workspace knows, or whose
    frontmatter is not plain. That is the same reading a save is held to."""
    pa = page_action()
    try:
        q = pa.WikiQuestion(ws, {"wiki": wiki, "file": rel})
        wall = pa.wall_sentence(ws)
        zone = pa.question_zone(q, wall)
        pages, _held, _missing = pa.question_pages(q, wall)
    except Exception:
        return None
    if q.status not in OPEN_STATES and q.status != "answered":
        return None
    asked = day(q.fm.get("asked"))
    later = day(q.fm.get("later"))
    parts = body_parts(q.text)
    if not parts["ask"]:
        return None
    verdict = str(q.fm.get("verdict") or "").strip().lower()
    origin = None
    for l in pa.tags_of(q.fm.get("origin"))[:1]:
        m = re.fullmatch(r"\[\[([^\]|#]+)\]\]", l.strip())
        if m and not m.group(1).startswith(("/", "~")) and ".." not in Path(m.group(1)).parts:
            for name in (m.group(1), m.group(1) + ".md", m.group(1) + ".txt"):
                f = (q.dir / name)
                if f.is_file() and not f.is_symlink() and f.resolve().parent.name != "" and (q.dir / "raw").resolve() in f.resolve().parents:
                    origin = {"name": Path(name).name, "href": link(f)}
                    break
            else:
                # An origin that is a wiki page (a question the lint made from an Open section): shown the way a
                # `pages:` link is, and only when that page is on the question's own side of every wall.
                page = pa.page_target(q, l)
                if page is not None:
                    if q.name == "Knowledge" or (zone and pa.page_zone_of(q, page) == zone):
                        origin = {"name": page.relative_to(q.dir).as_posix(), "href": link(page)}
    slug = pa.answer_slug(q.stem())
    answer_file = "Wikis/%s/raw/answers/%s - %s.md" % (wiki, today.strftime("%y%m%d"), slug)
    qpath = "Wikis/%s/%s" % (wiki, rel)
    due = q.status == "later" and later is not None and later <= today
    shown = q.status == "open" or due
    return {
        "wiki": wiki, "file": rel, "status": q.status, "title": parts["ask"], "why": parts["why"],
        "asked": asked.isoformat() if asked else "", "later": later.isoformat() if later else "",
        "due": bool(due), "shown": bool(shown), "zone": zone,
        "origin": origin,
        "pages": [{"name": p.relative_to(q.dir).as_posix(), "href": link(p)} for p in pages],
        "writes": dict({"answer": [answer_file, qpath], "later": [qpath], "close": [qpath]},
                       **({"decide": [answer_file, "Wikis/%s/wiki/decisions/%s - %s.md" % (wiki, today.strftime("%y%m%d"), slug), qpath]}
                          if wiki == "Meetings" else {})),
        "verdict": verdict if verdict in VERDICTS else "",
        "reason": clip(q.fm.get("verdict_reason") or "", LINE_MAX) if verdict in VERDICTS else "",
    }


DECISION_STATES = ("valid", "superseded", "withdrawn")


def decision_files(ws: Path) -> List[str]:
    """Each decision page of the Meetings wiki, as a path from the wiki's
    folder, at any depth of wiki/decisions/; a link or hidden file is passed over."""
    pa = page_action()
    base = Path(ws) / "Wikis" / "Meetings" / Path(*pa.WIKI_DECISION_DIR)
    out = []
    if not base.is_dir() or base.is_symlink():
        return out
    for p in sorted(base.rglob("*.md")):
        parts = p.relative_to(base).parts
        if p.is_symlink() or not p.is_file() or pa.SKIP & set(parts) or any(x.startswith((".", "_")) for x in parts):
            continue
        out.append(p.relative_to(base.parent.parent).as_posix())
    return out


def read_decision(ws: Path, lib, rel: str, link: Callable) -> Optional[dict]:
    """One decision page as the panel lists it, with the tags the walls place
    it by, or None for a page whose frontmatter cannot be read plainly, that
    is not `type: decision`, or whose zone is missing (fail closed: an
    unfinished page is placed nowhere)."""
    path = Path(ws) / "Wikis" / "Meetings" / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if lib.frontmatter_form_problem(text):
        return None
    fm = lib.parse_frontmatter_text(text)
    status = str(fm.get("status") or "").strip().lower()
    zone = fm.get("zone")
    if fm.get("type") != "decision" or status not in DECISION_STATES or not isinstance(zone, str) or not zone.strip():
        return None
    revisit = clip(fm.get("revisit") or "", LINE_MAX)
    return {"file": rel, "title": clip(fm.get("title") or path.stem, TITLE_MAX), "status": status,
            "decided": str(fm.get("decided") or "")[:10], "revisit": revisit, "zone": zone.strip(),
            "href": link(path)}


def build(ws: Path, C: Optional[dict], today: dt.date, link: Callable) -> Optional[dict]:
    """Everything the Context card asks of the wikis, or None where the workspace has
    nothing to build it from (no garrick_lib that reads the zones, or no
    zone)."""
    pa = page_action()
    lib = pa.prefs().lib(ws)
    need = ("parse_frontmatter_text", "frontmatter_form_problem", "load_context", "zone_of")
    if lib is None or not all(callable(getattr(lib, n, None)) for n in need):
        return None
    try:
        pa.wall_sentence(ws)
    except pa.Refused:
        return None
    zones = sorted(pa.zone_names(ws))
    views: Dict[str, object] = {}
    zone_info = []
    for zone in zones:
        try:
            views[zone] = pa.View(ws, lib, zone)
            zone_info.append({"zone": zone})
        except pa.Refused:
            pass
    buckets: Dict[str, dict] = {k: {"questions": [], "answered": 0, "decisions": [], "waiting": 0} for k in views}
    knowledge, answered_k = [], 0
    # A question whose own file carries a walls-family finding is not listed: a save would be refused.
    wall_files = {re.sub(r":\d+$", "", str(f.get("path"))) for f in (C or {}).get("findings", [])
                  if isinstance(f, dict) and pa.wallish(f.get("check"), f.get("message"))}
    # The kept check result is only as new as its time: a question file edited after it was made has not been
    # checked, so it is not shown but counted as waiting for the next check, per group and with no text. A result
    # made by this build is as new as the build; no result, or one that failed, leaves every question waiting.
    checked_at = None
    if C and not C.get("failed"):
        checked_at = C["at"] if isinstance(C.get("at"), (int, float)) else time.time()
    waiting_k = 0
    for wiki in WIKIS:
        for rel in question_files(ws, wiki):
            if "Wikis/%s/%s" % (wiki, rel) in wall_files:
                continue
            q = read_question(ws, wiki, rel, today, link)
            if q is None:
                continue
            try:
                stale = checked_at is None or os.stat(Path(ws) / "Wikis" / wiki / rel).st_mtime > checked_at
            except OSError:
                stale = True
            if stale:
                if wiki == "Knowledge":
                    waiting_k += 1
                else:
                    for key, view in views.items():
                        if view.ok(q["zone"]):
                            buckets[key]["waiting"] += 1
                continue
            if wiki == "Knowledge":
                if q["status"] == "answered":
                    answered_k += 1
                elif q["shown"]:
                    knowledge.append(q)
                continue
            for key, view in views.items():
                if not view.ok(q["zone"]):
                    continue
                if q["status"] == "answered":
                    buckets[key]["answered"] += 1
                elif q["shown"]:
                    buckets[key]["questions"].append(q)
    # A decision page is placed as a question is: by its zone, through the view's one test.
    # Only a valid decision with a revisit flag is listed (the assistant flags, the user settles).
    for rel in decision_files(ws):
        if "Wikis/Meetings/%s" % rel in wall_files:
            continue
        d = read_decision(ws, lib, rel, link)
        if d is None or d["status"] != "valid" or not d["revisit"]:
            continue
        for key, view in views.items():
            if view.ok(d["zone"]):
                buckets[key]["decisions"].append(d)
    # the menu's number: the open questions of each zone. A Knowledge question has no zone, so it is counted
    # once, apart (menu_knowledge), and in no zone's number.
    menu, per_group = {}, {}
    for info in zone_info:
        key = info["zone"]
        menu[key] = len(buckets[key]["questions"])
        # each group's own open count, for the menu to name apart (#384): never added up, and Knowledge apart
        per_group[key] = [{"h": key, "n": len(buckets[key]["questions"])}]
    return {"today": today.isoformat(), "root": str(ws), "zones": zone_info, "buckets": buckets, "knowledge": knowledge,
            "knowledge_answered": answered_k, "knowledge_waiting": waiting_k, "menu": menu, "menu_groups": per_group,
            "menu_knowledge": len(knowledge), "built": int(time.time() * 1000)}


LEDGER = ("System", "walls-allowed.json")
LEDGER_MAX = 500


def read_allowed(ws: Path, link: Callable) -> List[dict]:
    """What the user allowed, from System/walls-allowed.json as committed at HEAD (version 1: path, id, blob, rule, date, by). A missing or
    unreadable ledger, or an entry that does not read, is no allowance: nothing is shown for it. The token a finding
    matched is not in the ledger and not here. `state` says whether the file is still the one that was allowed (its
    git blob id), since an entry matches only on path, id and blob."""
    # The check honours only the ledger as committed at the workspace root's HEAD, so that is the copy listed: an
    # entry still only on disk allows nothing. No repository, or no committed ledger, is no allowance.
    try:
        done = subprocess.run(["git", "-C", str(ws), "show", "HEAD:" + "/".join(LEDGER)], capture_output=True, timeout=20,
                              stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            return []
        data = json.loads(done.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    rows = data.get("allowed") if isinstance(data, dict) and data.get("version") == 1 else None
    out: List[dict] = []
    for e in rows[:LEDGER_MAX] if isinstance(rows, list) else []:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e.get(k) for k in ("path", "id", "blob", "rule", "date", "by")):
            continue
        rel = Path(e["path"])
        if rel.is_absolute() or ".." in rel.parts or "\\" in e["path"]:
            continue
        full = Path(ws) / rel
        try:
            raw = full.read_bytes() if full.is_file() else None
        except OSError:
            raw = None
        state = "gone" if raw is None else "same" if hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest() == e["blob"] else "changed"
        out.append({"path": e["path"], "id": e["id"], "rule": e["rule"], "date": e["date"], "by": e["by"], "state": state,
                    "href": _href(link, full) if state != "gone" else ""})
    return out


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _href(link: Callable, path: Path) -> str:
    return link.attrs(path) if hasattr(link, "attrs") else 'href="%s"' % html.escape(str(link(path)), quote=True)


def allowed_rows(rows: List[dict]) -> str:
    """Allowed by you, for Settings (#542): each allowance with its file, rule, date and Remove, as the Context tab listed it;
    "" where there is none."""
    if not rows:
        return ""
    state = {"same": "", "changed": "The file has changed since, so this no longer allows anything.", "gone": "The file is gone."}
    items = []
    for r in rows:
        name = '<a %s>%s</a>' % (r["href"], _e(r["path"])) if r["href"] else '<span>%s</span>' % _e(r["path"])
        items.append('<li class="cxa-row" data-id="%s" data-path="%s"><div>%s</div><div class="muted">%s · allowed %s by %s%s</div>'
                     '<button type="button" class="act" data-unallow="1">Remove</button></li>' % (
                         _e(r["id"]), _e(r["path"]), name, _e(r["rule"]), _e(r["date"]), _e(r["by"]),
                         (" · " + state[r["state"]]) if state[r["state"]] else ""))
    return "".join(items)


def tab(findings: str) -> str:
    """The Context tab's inside: the questions panel and the cards under it, or nothing."""
    return '<div class="cx" id="cx">%s</div>' % findings if findings else ""


def counts_of(data: dict) -> dict:
    """The menu rows. "g" is each zone's groups with the open count of
    each, "k" the open Knowledge questions, which carry no zone: the app names
    them apart and adds none of them (#384). "z" is the count of each zone's
    default group, with no Knowledge in it, for a menu not yet updated;
    it is not added up either."""
    return {"z": dict(data.get("menu") or {}), "g": dict(data.get("menu_groups") or {}), "k": int(data.get("menu_knowledge") or 0)}


def tab_button(dot: str = "") -> str:
    """The tab. Its number is the count of the one place the card's Zone menu shows, set by the
    card's own script: a number made here would add up zones. `dot` is the
    title of a red dot."""
    mark = '<span class="dot critical" title="%s"></span>' % html.escape(dot, quote=True) if dot else ""
    return '<button type="button" role="tab" data-tab="questions">Context<span class="n" id="qp-tab-n"></span>%s</button>' % mark


CX_CSS = r"""
#allowed-settings ul{list-style:none;margin:8px 0 0;padding:0}.cxa-row{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.cxa-row .muted{grid-column:1}.cxa-row .act{grid-column:2;grid-row:1/3;align-self:center}
"""

CX_JS = r"""
(function(){var cx=document.getElementById('allowed-settings');if(!cx)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function say(s){if(window.GarrickSay)GarrickSay(s)}
/* Allowed by you: Remove puts the refusal back, through the page's walls-unallow */
cx.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-unallow]');if(!b)return;var r=b.closest('.cxa-row');if(!r)return;
var q={verb:'walls-unallow',path:r.getAttribute('data-path'),id:r.getAttribute('data-id')};
if(!host){say('A browser cannot change anything. Remove it in the Garrick app.');return}
if(!(window.GarrickAct&&GarrickAct(q,'Removing…')))host.postMessage({act:q});say('Removing…')});
var prev=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&q.verb==='walls-unallow'&&res&&res.ok){[].forEach.call(cx.querySelectorAll('.cxa-row'),function(r){if(r.getAttribute('data-path')===q.path&&r.getAttribute('data-id')===q.id)r.remove()})}
if(prev)return prev(q,res)}})();
"""
