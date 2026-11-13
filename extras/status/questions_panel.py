#!/usr/bin/env python3
"""questions_panel.py: the Questions panel's data and page (#224, point 9).

status.py builds the page; this file, beside it, decides what the panel may
show and draws it. The panel lists the wikis' open questions (a file each in
`Wikis/<Wiki>/questions/`) and Nurture's findings to open, one zone at a
time, and answers them through page_action.py: the panel itself calls no
model, and in a browser, where a page cannot act, it shows the questions and
copies what to say.

The walls decide what is listed. Every item is placed in a bucket, a zone, by
page_action.py's View.ok(zone), the one test a save is held to as well: a
question or a finding whose zone cannot be read, or that is not in the zone
shown, is placed nowhere, and so is never listed and never counted. The page is one
static file, as status.py's always is (it holds every zone's projects, todos
and Needs you questions, and the app picks the zone): every bucket is in the
page source and the script shows one. What a bucket holds is only what is on
the near side of its own view. A wall finding is never shown here; the Checks
card says it in its own words. Everything the page draws from the data is text
(textContent), never markup, a link or a command.

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
AGE_DAYS = {"any": 0, "week": 7, "month": 30}
WHY_MAX = 600
TITLE_MAX = 300
LINE_MAX = 200
VERDICTS = ("done", "stale", "duplicate")
ALL = "*"           # the choice that means every zone (#384)
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


def review_rows(ws: Path, nurture, C: Optional[dict], lib, ctx: dict, today: dt.date, link: Callable,
                views: Dict[str, object]) -> dict:
    """Nurture's findings to open, placed in the buckets by the walls.

    Returns {zone: {"read": [...]}}. A wall finding is never read here. A row
    appears in the bucket of the zone its file is in; a file with no zone the
    workspace knows is placed nowhere."""
    pa = page_action()
    out: Dict[str, dict] = {}
    if not nurture or not C:
        return out
    N, nctx = nurture
    root = Path(ws).resolve()
    seen = set()
    sorted_items = []
    for f in C.get("findings", []):
        try:
            sorted_items += [N.sort_item(nctx, i, light=True) for i in N.check_items(f)]
        except Exception:
            continue
    # A page with a wall finding on it has no row: a save would be refused, and the Checks card says the wall.
    walled_paths = {i.path for i in sorted_items if i.kind == "wall" or pa.wallish(i.check, i.message)} | {w for i in sorted_items if i.kind == "wall" for w in i.where}
    for item in sorted_items:
        if item.kind not in ("attribution", "judgment") or item.key in seen or item.path in walled_paths:
            continue
        seen.add(item.key)
        path = root / item.path
        if not str(path).startswith(str(root) + "/") or path.is_symlink() or not path.is_file():
            continue
        rel = item.path
        if not (rel.startswith("Wikis/Meetings/wiki/") or rel.startswith("Zones/")):
            continue
        zone = pa.page_zone(lib, ws, path)
        for key, view in views.items():
            if not view.ok(zone):
                continue
            out.setdefault(key, {"read": []})["read"].append(
                {"key": item.key, "path": rel, "check": clip(item.check, 40), "line": clip(item.message, LINE_MAX), "href": link(path)})
    return out


def group_views(zones: List[dict], zone: str = ALL) -> List[dict]:
    """The groups the panel shows for a Zone choice, *All* included (#384).

    `zones` is build()'s `zones` list. Each group is one zone: {"key": the
    zone's name, "zone", "kind": "zone", "heading": the zone's name}. Order is
    the zones' own. Nothing here joins groups: it only lists them."""
    return [{"key": z["zone"], "zone": z["zone"], "kind": "zone", "heading": z["zone"]}
            for z in zones if zone == ALL or z["zone"] == zone]


def can_sum(views: List[dict]) -> bool:
    """Whether one number may stand for these groups. Only for one: two zones
    may have a wall between them, and the page cannot show that they do not,
    so it fails closed and counts them apart."""
    return len(views) <= 1


def selections(zones: List[dict]) -> Dict[str, dict]:
    """group_views for every Zone choice the menu offers, with All as *:
    {"views": [...], "sum": can_sum(views)}. The page looks a choice up here
    and does not work groups out itself."""
    out: Dict[str, dict] = {}
    for zc in [ALL] + [z["zone"] for z in zones]:
        views = group_views(zones, zc)
        out[zc] = {"views": views, "sum": can_sum(views)}
    return out


def build(ws: Path, C: Optional[dict], nurture, today: dt.date, link: Callable) -> Optional[dict]:
    """Everything the Questions panel draws, or None where the workspace has
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
    ctx = lib.load_context(ws)
    zones = sorted(pa.zone_names(ws))
    views: Dict[str, object] = {}
    zone_info = []
    for zone in zones:
        try:
            views[zone] = pa.View(ws, lib, zone)
            zone_info.append({"zone": zone})
        except pa.Refused:
            pass
    buckets: Dict[str, dict] = {k: {"questions": [], "answered": 0, "review": {"read": []}, "decisions": [], "waiting": 0}
                                for k in views}
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
    for key, rows in review_rows(ws, nurture, C, lib, ctx, today, link, views).items():
        buckets[key]["review"] = rows
    # the menu's number: the open questions of each zone. A Knowledge question has no zone, so it is counted
    # once, apart (menu_knowledge), and in no zone's number.
    menu, per_group, per_find = {}, {}, {}
    for info in zone_info:
        key = info["zone"]
        menu[key] = len(buckets[key]["questions"])
        # each group's own open count, for the menu to name apart (#384): never added up, and Knowledge apart
        per_group[key] = [{"h": key, "n": len(buckets[key]["questions"])}]
        per_find[key] = {key: findings_in(buckets[key])}
    return {"today": today.isoformat(), "root": str(ws), "zones": zone_info, "select": selections(zone_info), "buckets": buckets, "knowledge": knowledge,
            "knowledge_answered": answered_k, "knowledge_waiting": waiting_k, "menu": menu, "menu_groups": per_group, "menu_findings": per_find,
            "menu_knowledge": len(knowledge), "built": int(time.time() * 1000)}


def findings_in(bucket: dict) -> int:
    """The Nurture findings a group holds to open."""
    return len((bucket.get("review") or {}).get("read") or [])


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
    """The panel's menu rows. "g" is each zone's groups with the open count of
    each, "k" the open Knowledge questions, which carry no zone: the app names
    them apart and adds none of them (#384). "z" is the count of each zone's
    default group, with no Knowledge in it, for a menu not yet updated;
    it is not added up either."""
    return {"z": dict(data.get("menu") or {}), "g": dict(data.get("menu_groups") or {}), "k": int(data.get("menu_knowledge") or 0)}


def tab_button(dot: str = "") -> str:
    """The tab. Its number is the open count of the zone shown, set by the
    panel's own script: a number made here would add up zones. `dot` is the
    title of a red dot."""
    mark = '<span class="dot critical" title="%s"></span>' % html.escape(dot, quote=True) if dot else ""
    return '<button type="button" role="tab" data-tab="questions">Context<span class="n" id="qp-tab-n"></span>%s</button>' % mark


def body(data: dict) -> str:
    """The panel's skeleton and its data. The data is JSON in a script element
    of its own (type application/json, so nothing in it runs)."""
    blob = json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return ('<div class="qp" id="qp"><h2 class="qp-title">Context Nurture</h2>'
            '<div class="qp-counts" id="qp-counts" role="status"></div>'
            '<div class="qp-bar">'
            '<label>Zone <select id="qp-zone"></select></label>'
            '<div class="qp-show"><span>List</span><div class="qp-switch" id="qp-source" role="group" aria-label="List">'
            '<button type="button" data-source="wiki" aria-pressed="true">Wiki questions</button>'
            '<button type="button" data-source="nurture" aria-pressed="false">Nurture findings</button></div></div>'
            '<label class="qp-wikiq-only">Wiki <select id="qp-wiki"><option value="">Both</option>'
            '<option value="Meetings">Meetings</option><option value="Knowledge">Knowledge</option></select></label>'
            '<label class="qp-wikiq-only">Age <select id="qp-age"><option value="any">Any</option>'
            '<option value="week">A week or more</option><option value="month">A month or more</option></select></label>'
            '</div>'
            '<div id="qp-wikiq"><div class="qp-cols"><ol class="qp-list" id="qp-list"></ol><div class="qp-open" id="qp-open"></div></div>'
            '<div id="qp-verdicts"></div><div id="qp-decisions"></div>'
            '<div class="gacts" id="qp-work"></div></div>'
            '<div id="qp-nurture" hidden></div>'
            '</div><script type="application/json" id="qp-data">%s</script>' % blob)


CSS = r"""
/* the Context tab (#224) */
.qp-title{margin:0 0 12px;font:600 20px/1.2 var(--display)}
.qp-counts{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px}.qp-counts .chip b{margin-right:4px}
.qp-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:0 0 14px;font-size:13px}
.qp-bar label{display:flex;align-items:center;gap:6px;color:var(--ink2)}
.qp-bar select,.qp select,.qp input[type=date]{font:inherit;font-size:13px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 8px}
.qp-cols{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,2fr);gap:16px;align-items:start}
@media(max-width:760px){.qp-cols{grid-template-columns:1fr}}
.qp-list{list-style:none;margin:0;padding:0;max-height:60vh;overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.qp-list li{padding:8px 10px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px}.qp-list li:last-child{border-bottom:0}
.qp-list li.on{background:var(--raise);box-shadow:inset 3px 0 0 var(--accent)}.qp-list li small{display:block;color:var(--muted);margin-top:2px}
.qp-open{border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:14px 16px;min-height:120px}
.qp-open h3{margin:0 0 8px;font:600 17px/1.3 var(--display)}.qp-open p{margin:0 0 10px;font-size:13px;color:var(--ink2)}
.qp-open textarea{width:100%;box-sizing:border-box;min-height:84px;font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px}
.qp-open .qp-links{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;margin:0 0 10px}
.qp-open .qp-writes{font-size:12px;color:var(--muted);margin:8px 0}.qp-open .gacts{margin-top:8px}
.qp-show{display:flex;align-items:center;gap:6px;color:var(--ink2)}
.qp-switch{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.qp-switch button{font:inherit;font-size:13px;color:var(--ink2);background:var(--surface);border:0;padding:4px 12px;cursor:pointer}
.qp-switch button+button{border-left:1px solid var(--line)}
.qp-switch button[aria-pressed=true]{color:var(--ink);background:var(--raise);box-shadow:inset 0 -2px 0 var(--accent)}
.qp-list li.qp-gh{cursor:default;font-weight:600;background:var(--bg);color:var(--ink2)}
.qp-gcount{display:flex;flex-wrap:wrap;gap:8px;align-items:center;width:100%}.qp-gcount strong{font-size:13px}
.qp-empty{padding:16px;color:var(--muted);font-size:13px}
.qp-group{margin:0 0 18px}.qp-group h3{margin:0 0 8px;font:600 16px/1.3 var(--display)}
.qp-row{display:grid;grid-template-columns:minmax(160px,1fr) minmax(220px,2fr) auto;gap:8px 14px;align-items:start;padding:10px 0;border-top:1px solid var(--line);font-size:13px}
.qp-row.refused{background:color-mix(in srgb,var(--critical) 8%,transparent)}
#qp-open .qp-say{color:var(--critical);margin:6px 0 0}
.qp-row .qp-first{color:var(--muted);display:block;margin-top:2px}.qp-row .qp-say{grid-column:1/-1;color:var(--critical)}
.qp-save{position:sticky;bottom:0;display:flex;gap:10px;align-items:center;padding:10px 0;background:var(--bg)}
body.nohost .qp-hostonly{display:none}body:not(.nohost) .qp-webonly{display:none}
"""

JS = r"""
(function(){var dataEl=document.getElementById('qp-data'),root=document.getElementById('qp');if(!dataEl||!root)return;
var D;try{D=JSON.parse(dataEl.textContent)}catch(e){return}
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,SK='garrick-questions';
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);if(v===null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,v)}catch(e){return null}}
function say(s){if(window.GarrickSay)GarrickSay(s)}
var $=function(id){return document.getElementById(id)};
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
/* A group heading: the zone's name in the zone's colour (D.zcls, from Settings), the rest and the count in the entry colour. Knowledge has no zone. */
function head(box,v,tail){var c=v.kind==='knowledge'?'':((D.zcls||{})[v.zone]||'');
if(!c||v.heading.indexOf(v.zone)!==0){box.appendChild(document.createTextNode(v.heading+(tail||'')));return box}
box.appendChild(el('span',c.trim(),v.zone));box.appendChild(document.createTextNode(v.heading.slice(v.zone.length)+(tail||'')));return box}
function link(name,href){var a=el('a','',name);a.setAttribute('href',href);return a}
var S={zone:'',source:'wiki',wiki:'',age:'any',cursor:'',gone:{},typed:{}};
try{Object.assign(S,JSON.parse(ss(SK)||'{}'))}catch(e){}
function keep(){ss(SK,JSON.stringify(S))}
/* S.gone only bridges the moment between a save and the rebuild after it: each entry holds the build it was saved against (the build's own time, never this browser's clock, so a clock apart from the server's cannot misjudge it), and an entry from an older build than this page's is dropped, so the data decides what shows */
function stamp(){return D.built||1}
(function(){var b=D.built||0,ch=false;Object.keys(S.gone).forEach(function(k){if(!(S.gone[k]>=b)){delete S.gone[k];ch=true}});if(ch)keep()})();
/* no zone chosen yet: the first zone, by name, with an open question in its default view; none has one, the first zone */
var zones=D.zones||[];if(S.zone!=='*'&&!zones.some(function(z){return z.zone===S.zone})){var fz=zones.filter(function(z){return((D.menu||{})[z.zone]||0)>0})[0]||zones[0];S.zone=fz?fz.zone:''}
/* the groups to show come from the page's own table (group_views in Python), never worked out here */
function sel(){return(D.select||{})[S.zone]||{views:[],sum:false}}
var EMPTY={questions:[],answered:0,decisions:[],waiting:0,review:{read:[]}};
function bucketOf(k){return(D.buckets||{})[k]||EMPTY}
function qviews(){return sel().views}
function key(q){return q.wiki+'/'+q.file}
/* the day after the build's today, in local time: the page's own today is the build's, a day with no clock in it */
function tomorrow(){var p=String(D.today||'').split('-').map(Number);if(p.length<3||p.some(isNaN))return'';var d=new Date(Date.UTC(p[0],p[1]-1,p[2]+1));return d.toISOString().slice(0,10)}
var REFUSED={};
function age(q){return Math.floor((new Date(D.today)-new Date(q.asked||D.today))/864e5)}
var AGE={any:0,week:7,month:30};
/* one entry per group: its own questions and its own count. Knowledge carries no party, so it is a group of its own. */
function groups(){var gs=qviews().map(function(v){var b=bucketOf(v.key);return{v:v,qs:b.questions.filter(function(q){return !S.gone[key(q)]}),answered:b.answered,decs:b.decisions||[],wait:b.waiting||0}});
var k=(D.knowledge||[]).filter(function(q){return !S.gone[key(q)]});
if(k.length||D.knowledge_answered||D.knowledge_waiting)gs.push({v:{key:'knowledge',heading:'Knowledge',kind:'knowledge'},qs:k,answered:D.knowledge_answered||0,decs:[],wait:D.knowledge_waiting||0});return gs}
function shown(){var flat=[],gs=groups();gs.forEach(function(g){g.items=g.qs.filter(function(q){return !q.verdict&&(!S.wiki||q.wiki===S.wiki)&&age(q)>=AGE[S.age]})
.sort(function(a,b){return(a.asked||'').localeCompare(b.asked||'')||a.file.localeCompare(b.file)});g.items.forEach(function(q){flat.push({q:q,g:g})})});return{gs:gs,flat:flat}}
function ekey(e){return e.g.v.key+'|'+key(e.q)}
function open(qs){return qs.filter(function(q){return !q.verdict}).length}
/* A number stands for several groups only where the table says one may (sum): otherwise each group counts alone. */
function wikiN(){if(!sel().sum)return null;var n=0;groups().forEach(function(g){n+=open(g.qs)});return n}
function nurtureN(){if(!sel().sum)return null;var n=0;
qviews().forEach(function(v){n+=bucketOf(v.key).review.read.length});return n}
function counts(){var c=$('qp-counts'),gs=groups();c.textContent='';
function chips(box,qs,ans,decs,wait){function chip(n,t){var s=el('span','chip');s.appendChild(el('b','',String(n)));s.appendChild(document.createTextNode(t));box.appendChild(s)}
chip(open(qs),'open');chip(qs.filter(function(q){return q.due}).length,'due today');chip(qs.filter(function(q){return q.verdict}).length,'proposed verdicts');chip(decs,'decisions to review');chip(ans,'answered, not worked in');if(wait)chip(wait,'waiting for the next check')}
if(sel().sum){var all=[],ans=0,dn=0,wn=0;gs.forEach(function(g){all=all.concat(g.qs);ans+=g.answered;dn+=g.decs.length;wn+=g.wait});chips(c,all,ans,dn,wn)}
else gs.forEach(function(g){var row=el('div','qp-gcount');row.appendChild(head(el('strong',''),g.v));chips(row,g.qs,g.answered,g.decs.length,g.wait);c.appendChild(row)});
var tn=$('qp-tab-n');if(tn){var n=wikiN();tn.textContent=n===null?'':String(n)}}
function answeredText(){var gs=groups().filter(function(g){return g.answered});if(sel().sum)return gs.reduce(function(n,g){return n+g.answered},0)+' answered, waiting to be worked in.';
return gs.map(function(g){return g.v.heading+' '+g.answered}).join('; ')+' answered, waiting to be worked in.'}
function fill(sel,opts,cur){sel.textContent='';opts.forEach(function(o){var e=el('option','',o[1]);e.value=o[0];if(o[0]===cur)e.selected=true;sel.appendChild(e)})}
function bar(){fill($('qp-zone'),[['*','All']].concat(zones.map(function(z){return[z.zone,z.zone]})),S.zone);
$('qp-wiki').value=S.wiki;$('qp-age').value=S.age;
[['wiki','Wiki questions',wikiN()],['nurture','Nurture findings',nurtureN()]].forEach(function(o){var b=root.querySelector('#qp-source [data-source="'+o[0]+'"]');
b.textContent=o[1]+(o[2]===null?'':' '+o[2]);b.setAttribute('aria-pressed',S.source===o[0]?'true':'false')});
root.querySelectorAll('.qp-wikiq-only').forEach(function(e){e.hidden=S.source!=='wiki'});
$('qp-wikiq').hidden=S.source!=='wiki';$('qp-nurture').hidden=S.source!=='nurture'}
/* ---- one question open at a time ---- */
function act(q,said){if(!host){say('Answer this in the Garrick app: a browser cannot change anything.');return false}
host.postMessage({act:q});say(said);return true}
function phrase(q,how,extra){var w=(q.wiki==='Knowledge'?'the Knowledge':'the Meetings')+' question';
return how==='decide'?'record '+w+' “'+q.title+'” as a decision, in these words: '+extra:how==='answer'?'answer '+w+' “'+q.title+'” with: '+extra:how==='later'?'put off '+w+' “'+q.title+'” until '+extra:'close '+w+' “'+q.title+'”'}
function copyWords(q,how,extra){var p=phrase(q,how,extra);if(window.GarrickCopy)GarrickCopy(p).then(function(){say('Copied. Paste it to your assistant.')})}
function list(){var v=shown(),ol=$('qp-list'),es=v.flat;ol.textContent='';
var many=v.gs.length>1;
if(!es.length&&!many){ol.appendChild(el('li','qp-empty','Nothing open here.'));$('qp-open').textContent='';return}
var at=es.findIndex(function(e){return ekey(e)===S.cursor});if(at<0){at=0;S.cursor=es.length?ekey(es[0]):''}
v.gs.forEach(function(g){if(many){var h=head(el('li','qp-gh'),g.v,' ('+open(g.qs)+')');h.setAttribute('role','presentation');ol.appendChild(h)}
g.items.forEach(function(q){var e=es.filter(function(x){return x.q===q&&x.g===g})[0],i=es.indexOf(e);
var li=el('li',i===at?'on':'',q.title);li.appendChild(el('small','',q.wiki+(q.asked?' · asked '+q.asked:'')+(q.due?' · due':'')));
li.onclick=function(){S.cursor=ekey(e);keep();list()};ol.appendChild(li)})});
if(!es.length){ol.appendChild(el('li','qp-empty','Nothing open here.'));$('qp-open').textContent='';return}
opened(es[at].q,es[at+1]||es[at-1]||null)}
function opened(q,nextE){var box=$('qp-open');box.textContent='';box.appendChild(el('h3','',q.title));
if(q.why)box.appendChild(el('p','',q.why));
var ls=el('div','qp-links');if(q.origin){ls.appendChild(el('span','','Came from'));ls.appendChild(link(q.origin.name,q.origin.href))}
if(q.pages.length){ls.appendChild(el('span','','Would change'));q.pages.forEach(function(p){ls.appendChild(link(p.name,p.href))})}
box.appendChild(ls);
var ta=el('textarea');ta.setAttribute('aria-label','Your answer, in your own words');ta.placeholder='Your answer, in your own words. Return saves and moves on.';
ta.value=S.typed[key(q)]||'';ta.oninput=function(){S.typed[key(q)]=ta.value;keep()};box.appendChild(ta);
var date=el('input');date.type='date';date.setAttribute('aria-label','Come back on');date.min=tomorrow();date.setAttribute('min',tomorrow());
var msg=el('p','qp-say');msg.hidden=!REFUSED[key(q)];msg.textContent=REFUSED[key(q)]||'';
var w=el('p','qp-writes');function writes(how){w.textContent='Saving writes: '+(q.writes[how]||[]).join(' and ')}writes('answer');box.appendChild(w);
var acts=el('div','gacts'),ans=el('button','act primary','Answer'),lat=el('button','act','Later'),clo=el('button','act','Close'),dec=el('button','act','Record as a decision');
[ans,lat,clo,dec].forEach(function(b){b.type='button'});
function req(how,extra){var r={verb:'question-'+how,wiki:q.wiki,file:q.file};if(how==='answer'||how==='decide')r.words=extra;if(how==='later')r.until=extra;return r}
function go(how,extra,said){if(!host){copyWords(q,how,extra);return}
if(act(req(how,extra),said)){S.gone[key(q)]=stamp();S.cursor=nextE?ekey(nextE):'';delete S.typed[key(q)];keep();counts();list()}}
function save(){var v=ta.value.trim();if(!v){ta.focus();return}go('answer',v,'Filing your answer…')}
ans.onclick=save;ta.onkeydown=function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();save()}};
function warn(t){msg.textContent=t;msg.hidden=false;say(t)}
lat.onclick=function(){if(!date.value){date.focus();warn('Pick the day to come back on.');return}
if(date.value<=D.today){date.focus();warn('Pick a day after today.');return}
delete REFUSED[key(q)];msg.hidden=true;go('later',date.value,'Putting it off…')};
clo.onclick=function(){go('close','','Closing…')};
dec.onclick=function(){var v=ta.value.trim();if(!v){ta.focus();say('Say the decision in your own words first.');return}go('decide',v,'Recording the decision…')};
if(!q.writes.decide){dec.disabled=true;dec.title='A Knowledge question has no zone and no parties for a decision to carry'}
else{dec.title='Files your words as the raw answer and as a decision that stands as valid';dec.addEventListener('mouseover',function(){writes('decide')})}
[ans,date,lat,clo,dec].forEach(function(b){acts.appendChild(b)});box.appendChild(acts);box.appendChild(msg);
lat.addEventListener('mouseover',function(){writes('later')});clo.addEventListener('mouseover',function(){writes('close')});ans.addEventListener('mouseover',function(){writes('answer')});
if(!host)box.appendChild(el('p','hint','In a browser this page cannot save: each button copies what to say to your assistant.'))}
/* ---- proposed verdicts, one by one or all at once, each a close ---- */
var line=[];
function drain(){var q=line.shift();if(!q)return;if(S.gone[key(q)])return drain();S.gone[key(q)]=stamp();keep();act({verb:'question-close',wiki:q.wiki,file:q.file},'Closing…')}
function vlist(){var box=$('qp-verdicts'),gs=groups().filter(function(g){return g.qs.some(function(q){return q.verdict})});box.textContent='';
gs.forEach(function(g){var vs=g.qs.filter(function(q){return q.verdict});
var h=el('div','qp-group');h.appendChild(el('h3','',groups().length>1?'Proposed verdicts · '+g.v.heading:'Proposed verdicts'));
vs.forEach(function(q){var r=el('div','qp-row');r.appendChild(el('div','',q.title));r.appendChild(el('div','',q.verdict+(q.reason?': '+q.reason:'')));
var b=el('button','act','Accept');b.type='button';b.onclick=function(){if(!host){copyWords(q,'close');return}line=[q];drain();all()};
r.appendChild(b);h.appendChild(r)});
/* Accept all closes the group's own, one question at a time, each as a save from its own view */
var every=el('button','act primary','Accept all');every.type='button';every.onclick=function(){if(!host){say('Accept them one at a time in a browser.');return}line=vs.slice();drain();all()};
h.appendChild(every);box.appendChild(h)})}
/* ---- decisions the assistant flagged for a second look, per group: opened in the note app, settled by hand ---- */
function dlist(){var box=$('qp-decisions'),gs=groups().filter(function(g){return g.decs.length});box.textContent='';
gs.forEach(function(g){var h=el('div','qp-group');h.appendChild(el('h3','',groups().length>1?'Decisions to review · '+g.v.heading:'Decisions to review'));
g.decs.forEach(function(d){var r=el('div','qp-row');r.appendChild(d.href?link(d.title,d.href):el('span','',d.title));
r.appendChild(el('div','',(d.decided?'Decided '+d.decided+'. ':'')+'Revisit: '+d.revisit));h.appendChild(r)});box.appendChild(h)})}
/* ---- Work them in: the route Process the Inbox takes ---- */
function work(){var box=$('qp-work');box.textContent='';if(!groups().some(function(g){return g.answered}))return;
var b=el('button','act primary','Work them in');b.type='button';b.setAttribute('data-request','work through the open questions');
b.setAttribute('data-folder',D.root||'');b.title='Hand “work through the open questions” to your assistant';box.appendChild(b);
box.appendChild(el('span','hint',answeredText()))}
/* Open in Claude, and in Codex where installed (#433): one finding handed to a session, with its path, the check and its line. In a browser, or with neither installed, the request is copied. */
var OPENS=[['claude','Open in Claude'],['codex','Open in Codex']];
function handOver(r){var box=el('div','gacts'),say_='Look at this finding with me: '+r.path+', check '+r.check+(r.line?', '+r.line:'')+'. Open the file, say what is wrong and propose the edit; change nothing until I say yes.',
on=(document.body.dataset.launchers||'').split(',');
var ls=host?OPENS.filter(function(o){return on.indexOf(o[0])>=0}):[];
ls.forEach(function(o){var b=el('button','act',o[1]);b.type='button';b.setAttribute('data-launch',o[0]);b.setAttribute('data-folder',D.root||'');b.setAttribute('data-phrase',say_);b.setAttribute('data-say','Opening '+o[1].slice(8)+' on this finding…');box.appendChild(b)});
if(!ls.length){var c=el('button','act','Copy request');c.type='button';c.setAttribute('data-request',say_);c.setAttribute('data-folder',D.root||'');box.appendChild(c)}
return box}
function review(){var box=$('qp-nurture');box.textContent='';var any=false;
qviews().forEach(function(v){var rd=bucketOf(v.key).review.read;if(!rd.length)return;any=true;
var d=el('details','qp-group');d.appendChild(el('summary','',(sel().views.length>1?v.heading+': ':'')+'Findings to open ('+rd.length+')'));
rd.forEach(function(r){var p=el('div','qp-row');p.appendChild(link(r.path,r.href));p.appendChild(el('div','',r.check+(r.line?': '+r.line:'')));p.appendChild(handOver(r));d.appendChild(p)});box.appendChild(d)});
if(!any){box.appendChild(el('div','qp-empty','No findings to open here.'));return}
var foot=el('div','qp-save'),web=el('button','act qp-webonly','Nurture in the chat');web.type='button';web.setAttribute('data-request','nurture the context');web.setAttribute('data-folder',D.root||'');
foot.appendChild(web);box.appendChild(foot)}
var prevActed=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&/^question-/.test(q.verb)&&q.wiki&&q.file&&res&&!res.ok){var qk=q.wiki+'/'+q.file;delete S.gone[qk];REFUSED[qk]=res.say||'That did not work.';
var at=shown().flat.filter(function(e){return key(e.q)===qk})[0];if(at)S.cursor=ekey(at);keep();counts();list()}
if(q&&q.verb==='question-close'&&line.length)drain();
if(prevActed)return prevActed(q,res)};
function all(){bar();counts();list();vlist();dlist();work();review();keep()}
$('qp-zone').onchange=function(){S.zone=this.value;S.cursor='';all()};
root.querySelectorAll('#qp-source button').forEach(function(b){b.onclick=function(){S.source=b.getAttribute('data-source');all()}});
$('qp-wiki').onchange=function(){S.wiki=this.value;S.cursor='';all()};
$('qp-age').onchange=function(){S.age=this.value;S.cursor='';all()};
window.GarrickQuestions={open:function(){if(window.StatusTab)StatusTab('questions');window.scrollTo(0,0);var t=root.querySelector('textarea');if(t)t.focus()}};
all()})();
"""


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
