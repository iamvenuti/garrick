#!/usr/bin/env python3
"""questions_panel.py: the Questions panel's data and page (#224, point 9).

status.py builds the page; this file, beside it, decides what the panel may
show and draws it. The panel lists the wikis' open questions (a file each in
`Wikis/<Wiki>/questions/`) and Nurture's attribution findings, one zone at a
time, and answers them through page_action.py: the panel itself calls no
model, and in a browser, where a page cannot act, it shows the questions and
copies what to say.

The walls decide what is listed. Every item is placed in a bucket, a zone and
a party of it, by page_action.py's View.ok(tags), the one test a save is held
to as well: a question or a finding whose parties cannot be read plainly, or
that is not wholly on the near side of the zone shown, is placed nowhere, and
so is never listed, never counted and never offered as a pick. Only the
buckets are written into the page, so a hidden zone's items are not in it. A
wall finding is never shown here; the Checks card says it in its own words.
Everything the page draws from the data is text (textContent), never markup,
a link or a command.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
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
    walls cannot read: a question whose pages sit on both sides of a wall,
    whose parties are unknown or walled from each other, or whose frontmatter
    is not plain. That is the same reading a save is held to."""
    pa = page_action()
    try:
        q = pa.WikiQuestion(ws, {"wiki": wiki, "file": rel})
        wall = pa.wall_sentence(ws)
        tags = pa.question_parties(q, wall)
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
    slug = pa.answer_slug(q.stem())
    answer_file = "Wikis/%s/raw/answers/%s - %s.md" % (wiki, today.strftime("%y%m%d"), slug)
    qpath = "Wikis/%s/%s" % (wiki, rel)
    due = q.status == "later" and later is not None and later <= today
    shown = q.status == "open" or due
    return {
        "wiki": wiki, "file": rel, "status": q.status, "title": parts["ask"], "why": parts["why"],
        "asked": asked.isoformat() if asked else "", "later": later.isoformat() if later else "",
        "due": bool(due), "shown": bool(shown), "parties": sorted(tags), "zone": str(q.fm.get("zone") or "").strip(),
        "origin": origin,
        "pages": [{"name": p.relative_to(q.dir).as_posix(), "href": link(p)} for p in pages],
        "writes": {"answer": [answer_file, qpath], "later": [qpath], "close": [qpath]},
        "verdict": verdict if verdict in VERDICTS else "",
        "reason": clip(q.fm.get("verdict_reason") or "", LINE_MAX) if verdict in VERDICTS else "",
    }


def first_line(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return clip(s, LINE_MAX)
    return ""


def review_rows(ws: Path, nurture, C: Optional[dict], lib, ctx: dict, today: dt.date, link: Callable,
                views: Dict[str, object]) -> dict:
    """Nurture's attribution findings, placed in the buckets by the walls.

    Returns {bucket key: {"entities": [...], "people": [...], "read": [...]}}.
    A wall finding is never read here. A person row appears in the bucket its
    page's parties fit, and only with a proposal whose entity page fits it
    too. An entity page that does not say whose it is has no party the walls
    could hold it to, so it is offered only in the unattributed view, for the
    parties of the zone chosen there. A page whose frontmatter cannot be read
    plainly is placed nowhere."""
    pa = page_action()
    out: Dict[str, dict] = {}
    if not nurture or not C:
        return out
    N, nctx = nurture
    later = pa.read_later(ws)
    index = lib.entity_names(ws) if callable(getattr(lib, "entity_names", None)) else []
    by_rel = {e["rel"]: e for e in index}
    root = Path(ws).resolve()
    seen = set()
    sorted_items = []
    for f in C.get("findings", []):
        try:
            sorted_items += [N.sort_item(nctx, i) for i in N.check_items(f)]
        except Exception:
            continue
    # A page with a wall finding on it has no row: a save would be refused, and the Checks card says the wall.
    walled_paths = {i.path for i in sorted_items if i.kind == "wall"} | {w for i in sorted_items if i.kind == "wall" for w in i.where}
    for item in sorted_items:
        if item.kind not in ("attribution", "judgment") or item.key in seen or item.path in walled_paths:
            continue
        seen.add(item.key)
        if later.get(item.key, "") > today.isoformat():
            continue
        path = root / item.path
        if not str(path).startswith(str(root) + "/") or path.is_symlink() or not path.is_file():
            continue
        rel = item.path
        people = item.check == "people" and item.kind == "attribution" and rel.startswith("Wikis/Meetings/wiki/people/") \
            and item.message.startswith((N.NO_ORGANISATION, N.NO_EMPLOYER, N.ORGANISATION_ASK))
        ents = item.check == "meetings" and item.kind == "attribution" and rel.startswith("Wikis/Meetings/wiki/entities/") \
            and item.message.startswith(N.NO_ENTITY_PARTY)
        if ents:
            e = next((x for x in index if x["rel"] == rel[len("Wikis/Meetings/wiki/entities/"):-3]), None)
            if e is None or e["tagged"] or e["misread"] or e["parties"]:
                continue
            row = {"key": item.key, "do": "answer", "path": rel, "title": clip(e["title"], LINE_MAX), "href": link(path)}
            for key, view in views.items():
                if key.startswith("unattributed|"):
                    out.setdefault(key, {"entities": [], "people": [], "read": []})["entities"].append(row)
            continue
        tags = pa.page_party_tags(lib, ws, path)
        if not tags:
            continue                        # parties cannot be read plainly: walled
        if people:
            title = clip(path.stem.replace("-", " "), LINE_MAX)
            try:
                from_fm = lib.parse_frontmatter_text(path.read_text(encoding="utf-8")).get("title")
                title = clip(from_fm or title, LINE_MAX)
            except (OSError, UnicodeError):
                continue
            prop = None
            m = re.fullmatch(r"\[\[wiki/entities/([^\]|#]+)\]\]", item.proposal or "")
            if m and m.group(1) in by_rel:
                prop = by_rel[m.group(1)]
            for key, view in views.items():
                if key.startswith("unattributed|") or not view.ok(tags):
                    continue
                row = {"key": item.key, "do": "organisation", "path": rel, "title": title, "href": link(path), "proposal": None}
                if prop is not None:
                    if not view.ok(prop["parties"]):
                        continue
                    row["proposal"] = {"rel": prop["rel"], "title": clip(prop["title"], LINE_MAX),
                                       "line": first_line(prop["path"])}
                out.setdefault(key, {"entities": [], "people": [], "read": []})["people"].append(row)
            continue
        # a judgment finding, or an attribution this page cannot answer: read-only, the path and the check's name
        if not (rel.startswith("Wikis/Meetings/wiki/") or rel.startswith("Zones/")):
            continue
        for key, view in views.items():
            if key.startswith("unattributed|") or not view.ok(tags):
                continue
            out.setdefault(key, {"entities": [], "people": [], "read": []})["read"].append(
                {"key": item.key, "path": rel, "check": clip(item.check, 40), "href": link(path)})
    return out


def pick_lists(ws: Path, lib, views: Dict[str, object]) -> Dict[str, dict]:
    """What *Another page* may offer in each bucket: entity pages by title and
    alias, and party tags plus none. Only pages on the near side of the bucket
    (View.ok on the page's own parties); in the unattributed view the parties
    of the zone chosen."""
    out = {}
    index = lib.entity_names(ws) if callable(getattr(lib, "entity_names", None)) else []
    ctx = lib.load_context(ws)
    for key, view in views.items():
        if key.startswith("unattributed|"):
            out[key] = {"entities": [], "parties": [{"tag": t, "name": str((ctx["parties"].get(t) or {}).get("party") or t)}
                                                    for t in sorted(view.parties)] + [{"tag": "none", "name": "none"}]}
            continue
        ents = []
        for e in index:
            if e["misread"] or not e["tagged"] or not e["parties"] or not view.ok(e["parties"]):
                continue
            names = [n for n in e["names"] if n not in (e["title"], e["rel"])]
            ents.append({"rel": e["rel"], "title": clip(e["title"], LINE_MAX), "aliases": [clip(n, LINE_MAX) for n in names[:6]]})
        out[key] = {"entities": ents, "parties": []}
    return out


def build(ws: Path, C: Optional[dict], nurture, today: dt.date, link: Callable) -> Optional[dict]:
    """Everything the Questions panel draws, or None where the workspace has
    nothing to build it from (no garrick_lib that reads the walls, or no
    zone with a party)."""
    pa = page_action()
    lib = pa.prefs().lib(ws)
    need = ("parse_frontmatter_text", "frontmatter_form_problem", "load_context", "walled", "entity_names")
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
        parties = sorted(t for t, p in (ctx.get("parties") or {}).items() if str(p.get("zone") or "").strip() == zone)
        if not parties:
            continue
        info = {"zone": zone, "scopes": [], "default": ""}
        try:
            views["%s|" % zone] = pa.View(ws, lib, zone, None)
        except pa.Refused:
            # a wall divides this zone's own parties: one bucket for each party, and no view of all of them
            for tag in parties:
                try:
                    views["%s|%s" % (zone, tag)] = pa.View(ws, lib, zone, tag)
                    info["scopes"].append({"tag": tag, "name": str((ctx["parties"].get(tag) or {}).get("party") or tag)})
                except pa.Refused:
                    pass
            info["default"] = info["scopes"][0]["tag"] if info["scopes"] else ""
        try:
            views["unattributed|%s" % zone] = pa.View(ws, lib, pa.UNATTRIBUTED, zone)
        except pa.Refused:
            pass
        if any(k.startswith(zone + "|") for k in views):
            zone_info.append(info)
    buckets: Dict[str, dict] = {k: {"questions": [], "answered": 0, "review": {"entities": [], "people": [], "read": []},
                                    "picks": {"entities": [], "parties": []}} for k in views}
    knowledge = []
    for wiki in WIKIS:
        for rel in question_files(ws, wiki):
            q = read_question(ws, wiki, rel, today, link)
            if q is None:
                continue
            if wiki == "Knowledge":
                if q["status"] != "answered" and q["shown"]:
                    knowledge.append(q)
                continue
            for key, view in views.items():
                if key.startswith("unattributed|") or q["zone"] != view.zone or not view.ok(q["parties"]):
                    continue
                if q["status"] == "answered":
                    buckets[key]["answered"] += 1
                elif q["shown"]:
                    buckets[key]["questions"].append(q)
    for key, rows in review_rows(ws, nurture, C, lib, ctx, today, link, views).items():
        buckets[key]["review"] = rows
    for key, picks in pick_lists(ws, lib, views).items():
        buckets[key]["picks"] = picks
    answered_k = 0
    for wiki, rel in ((w, r) for w in ("Knowledge",) for r in question_files(ws, "Knowledge")):
        q = read_question(ws, wiki, rel, today, link)
        if q and q["status"] == "answered":
            answered_k += 1
    # the menu's number: the open questions of each zone's default bucket, Knowledge's included
    menu = {}
    for info in zone_info:
        key = "%s|%s" % (info["zone"], info["default"])
        if key in buckets:
            menu[info["zone"]] = len(buckets[key]["questions"]) + len(knowledge)
    return {"today": today.isoformat(), "root": str(ws), "zones": zone_info, "buckets": buckets, "knowledge": knowledge,
            "knowledge_answered": answered_k, "menu": menu}


def counts_of(data: dict) -> dict:
    """The panel's menu rows: the open count of each zone, for the app to
    add up over the zones it shows."""
    return {"z": dict(data.get("menu") or {})}


def tab_button() -> str:
    """The tab. Its number is the open count of the zone shown, set by the
    panel's own script: a number made here would add up zones."""
    return '<button type="button" role="tab" data-tab="questions">Questions<span class="n" id="qp-tab-n"></span></button>'


def body(data: dict) -> str:
    """The panel's skeleton and its data. The data is JSON in a script element
    of its own (type application/json, so nothing in it runs)."""
    blob = json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return ('<div class="qp" id="qp">'
            '<div class="qp-counts" id="qp-counts" role="status"></div>'
            '<div class="qp-bar">'
            '<label>Zone <select id="qp-zone"></select></label>'
            '<label>Show <select id="qp-source"><option value="wiki">Wiki questions</option>'
            '<option value="nurture">Nurture findings</option></select></label>'
            '<label class="qp-wikiq-only">Wiki <select id="qp-wiki"><option value="">Both</option>'
            '<option value="Meetings">Meetings</option><option value="Knowledge">Knowledge</option></select></label>'
            '<label id="qp-party-l">Party <select id="qp-party"></select></label>'
            '<label class="qp-wikiq-only">Age <select id="qp-age"><option value="any">Any</option>'
            '<option value="week">A week or more</option><option value="month">A month or more</option></select></label>'
            '</div>'
            '<div id="qp-wikiq"><div class="qp-cols"><ol class="qp-list" id="qp-list"></ol><div class="qp-open" id="qp-open"></div></div>'
            '<div id="qp-verdicts"></div>'
            '<div class="gacts" id="qp-work"></div></div>'
            '<div id="qp-nurture" hidden></div>'
            '</div><script type="application/json" id="qp-data">%s</script>' % blob)


CSS = r"""
/* the Questions panel (#224) */
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
.qp-empty{padding:16px;color:var(--muted);font-size:13px}
.qp-group{margin:0 0 18px}.qp-group h3{margin:0 0 8px;font:600 16px/1.3 var(--display)}
.qp-row{display:grid;grid-template-columns:minmax(160px,1fr) minmax(220px,2fr) auto;gap:8px 14px;align-items:start;padding:10px 0;border-top:1px solid var(--line);font-size:13px}
.qp-row.refused{background:color-mix(in srgb,var(--critical) 8%,transparent)}
.qp-row .qp-first{color:var(--muted);display:block;margin-top:2px}.qp-row .qp-say{grid-column:1/-1;color:var(--critical)}
.qp-row .qp-choice{display:flex;flex-wrap:wrap;gap:4px 10px}.qp-row .qp-choice label{display:flex;align-items:center;gap:4px;white-space:nowrap}
.qp-row .qp-extra{grid-column:2/-1;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.qp-row .qp-extra input[type=text],.qp-row .qp-extra input[list]{font:inherit;font-size:13px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:4px 8px;min-width:200px}
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
function link(name,href){var a=el('a','',name);a.setAttribute('href',href);return a}
var S={zone:'',party:'',source:'wiki',wiki:'',age:'any',cursor:'',gone:{},typed:{}};
try{Object.assign(S,JSON.parse(ss(SK)||'{}'))}catch(e){}
function keep(){ss(SK,JSON.stringify(S))}
var zones=D.zones||[];if(!zones.some(function(z){return z.zone===S.zone}))S.zone=zones.length?zones[0].zone:'';
function zinfo(){return zones.filter(function(z){return z.zone===S.zone})[0]||{scopes:[]}}
function scoped(){return zinfo().scopes.length>0}
function pkey(){var z=zinfo();return scoped()?(z.scopes.some(function(s){return s.tag===S.party})?S.party:z.default):''}
var EMPTY={questions:[],answered:0,review:{entities:[],people:[],read:[]},picks:{entities:[],parties:[]}};
function bucket(){return(D.buckets||{})[S.zone+'|'+pkey()]||EMPTY}
function ubucket(){return(D.buckets||{})['unattributed|'+S.zone]||EMPTY}
function key(q){return q.wiki+'/'+q.file}
function pool(){return bucket().questions.concat(D.knowledge||[]).filter(function(q){return !S.gone[key(q)]})}
function age(q){return Math.floor((new Date(D.today)-new Date(q.asked||D.today))/864e5)}
var AGE={any:0,week:7,month:30};
function visible(){return pool().filter(function(q){return !q.verdict&&(!S.wiki||q.wiki===S.wiki)&&age(q)>=AGE[S.age]})
.sort(function(a,b){return(a.asked||'').localeCompare(b.asked||'')||a.file.localeCompare(b.file)})}
function answeredN(){return bucket().answered+(D.knowledge_answered||0)}
function counts(){var all=pool(),c=$('qp-counts');c.textContent='';
function chip(n,t){var s=el('span','chip');s.appendChild(el('b','',String(n)));s.appendChild(document.createTextNode(t));c.appendChild(s)}
chip(all.filter(function(q){return !q.verdict}).length,'open');chip(all.filter(function(q){return q.due}).length,'due today');var tn=$('qp-tab-n');if(tn)tn.textContent=String(all.filter(function(q){return !q.verdict}).length);
chip(all.filter(function(q){return q.verdict}).length,'proposed verdicts');chip(answeredN(),'answered, not worked in')}
function fill(sel,opts,cur){sel.textContent='';opts.forEach(function(o){var e=el('option','',o[1]);e.value=o[0];if(o[0]===cur)e.selected=true;sel.appendChild(e)})}
function bar(){fill($('qp-zone'),zones.map(function(z){return[z.zone,z.zone]}),S.zone);
$('qp-party-l').hidden=!scoped();if(scoped())fill($('qp-party'),zinfo().scopes.map(function(s){return[s.tag,s.name]}),pkey());
$('qp-source').value=S.source;$('qp-wiki').value=S.wiki;$('qp-age').value=S.age;
root.querySelectorAll('.qp-wikiq-only').forEach(function(e){e.hidden=S.source!=='wiki'});
$('qp-wikiq').hidden=S.source!=='wiki';$('qp-nurture').hidden=S.source!=='nurture'}
/* ---- one question open at a time ---- */
function act(q,said){if(!host){say('Answer this in the Garrick app: a browser cannot change anything.');return false}
host.postMessage({act:q});say(said);return true}
function phrase(q,how,extra){var w=(q.wiki==='Knowledge'?'the Knowledge':'the Meetings')+' question';
return how==='answer'?'answer '+w+' “'+q.title+'” with: '+extra:how==='later'?'put off '+w+' “'+q.title+'” until '+extra:'close '+w+' “'+q.title+'”'}
function copyWords(q,how,extra){var p=phrase(q,how,extra);if(window.GarrickCopy)GarrickCopy(p).then(function(){say('Copied. Paste it to your assistant.')})}
function list(){var qs=visible(),ol=$('qp-list');ol.textContent='';
if(!qs.length){ol.appendChild(el('li','qp-empty','Nothing open here.'));$('qp-open').textContent='';return}
var at=qs.findIndex(function(q){return key(q)===S.cursor});if(at<0){at=0;S.cursor=key(qs[0])}
qs.forEach(function(q,i){var li=el('li',i===at?'on':'',q.title);li.appendChild(el('small','',q.wiki+(q.asked?' · asked '+q.asked:'')+(q.due?' · due':'')));
li.onclick=function(){S.cursor=key(q);keep();list()};ol.appendChild(li)});
opened(qs[at],qs[at+1]||qs[at-1]||null)}
function opened(q,next){var box=$('qp-open');box.textContent='';box.appendChild(el('h3','',q.title));
if(q.why)box.appendChild(el('p','',q.why));
var ls=el('div','qp-links');if(q.origin){ls.appendChild(el('span','','Came from'));ls.appendChild(link(q.origin.name,q.origin.href))}
if(q.pages.length){ls.appendChild(el('span','','Would change'));q.pages.forEach(function(p){ls.appendChild(link(p.name,p.href))})}
box.appendChild(ls);
var ta=el('textarea');ta.setAttribute('aria-label','Your answer, in your own words');ta.placeholder='Your answer, in your own words. Return saves and moves on.';
ta.value=S.typed[key(q)]||'';ta.oninput=function(){S.typed[key(q)]=ta.value;keep()};box.appendChild(ta);
var date=el('input');date.type='date';date.setAttribute('aria-label','Come back on');
var w=el('p','qp-writes');function writes(how){w.textContent='Saving writes: '+(q.writes[how]||[]).join(' and ')}writes('answer');box.appendChild(w);
var acts=el('div','gacts'),ans=el('button','act primary','Answer'),lat=el('button','act','Later'),clo=el('button','act','Close'),dec=el('button','act','Record as a decision');
[ans,lat,clo,dec].forEach(function(b){b.type='button'});
function req(how,extra){var r={verb:'question-'+how,wiki:q.wiki,file:q.file};if(how==='answer')r.words=extra;if(how==='later')r.until=extra;return r}
function go(how,extra,said){if(!host){copyWords(q,how,extra);return}
if(act(req(how,extra),said)){S.gone[key(q)]=1;S.cursor=next?key(next):'';delete S.typed[key(q)];keep();counts();list()}}
function save(){var v=ta.value.trim();if(!v){ta.focus();return}go('answer',v,'Filing your answer…')}
ans.onclick=save;ta.onkeydown=function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();save()}};
lat.onclick=function(){if(!date.value){date.focus();say('Pick the day to come back on.');return}go('later',date.value,'Putting it off…')};
clo.onclick=function(){go('close','','Closing…')};
dec.onclick=function(){if(host)act({verb:'question-decide',wiki:q.wiki,file:q.file},'Recording as a decision…');else say('Recording a decision is not built yet.')};
dec.title='Not built yet: it says so and writes nothing';
[ans,date,lat,clo,dec].forEach(function(b){acts.appendChild(b)});box.appendChild(acts);
lat.addEventListener('mouseover',function(){writes('later')});clo.addEventListener('mouseover',function(){writes('close')});ans.addEventListener('mouseover',function(){writes('answer')});
if(!host)box.appendChild(el('p','hint','In a browser this page cannot save: each button copies what to say to your assistant.'))}
/* ---- proposed verdicts, one by one or all at once, each a close ---- */
var line=[];
function drain(){var q=line.shift();if(!q)return;S.gone[key(q)]=1;keep();act({verb:'question-close',wiki:q.wiki,file:q.file},'Closing…')}
function vlist(){var box=$('qp-verdicts'),vs=pool().filter(function(q){return q.verdict});box.textContent='';if(!vs.length)return;
var h=el('div','qp-group');h.appendChild(el('h3','','Proposed verdicts'));
vs.forEach(function(q){var r=el('div','qp-row');r.appendChild(el('div','',q.title));r.appendChild(el('div','',q.verdict+(q.reason?': '+q.reason:'')));
var b=el('button','act','Accept');b.type='button';b.onclick=function(){if(!host){copyWords(q,'close');return}line=[q];drain();counts();vlist();list()};
r.appendChild(b);h.appendChild(r)});
var all=el('button','act primary','Accept all');all.type='button';all.onclick=function(){if(!host){say('Accept them one at a time in a browser.');return}line=vs.slice();drain();counts();vlist();list()};
h.appendChild(all);box.appendChild(h)}
/* ---- Work them in: the route Process the Inbox takes ---- */
function work(){var box=$('qp-work');box.textContent='';var n=answeredN();if(!n)return;
var b=el('button','act primary','Work them in');b.type='button';b.setAttribute('data-request','work through the open questions');
b.setAttribute('data-folder',D.root||'');b.title='Hand “work through the open questions” to your assistant';box.appendChild(b);
box.appendChild(el('span','hint',n+' answered, waiting to be worked in.'))}
/* ---- the review page for Nurture's findings: one row each, the proposal chosen, one Save ---- */
var rows=[];
function mk(tag,type,name,value,on){var i=el(tag);i.type=type;if(name)i.name=name;i.value=value;i.checked=!!on;return i}
function opt(parent,v,t,on){var l=el('label'),i=mk('input','radio',parent.dataset.name,v,on);l.appendChild(i);l.appendChild(document.createTextNode(t));parent.appendChild(l);return i}
function rowFor(r,bk,kind){var row=el('div','qp-row'),left=el('div'),prop=r.proposal,hasProp=kind==='organisation'&&!!prop;
left.appendChild(r.href?link(r.title,r.href):el('span','',r.title));row.appendChild(left);
var mid=el('div');
if(kind==='organisation'){if(prop){mid.appendChild(el('span','','Works at '));mid.appendChild(el('b','',prop.title));if(prop.line)mid.appendChild(el('span','qp-first',prop.line))}else mid.appendChild(el('span','','No page is proposed'))}
else mid.appendChild(el('span','','Whose is it: a party, or none?'));
row.appendChild(mid);
var ch=el('div','qp-choice');ch.dataset.name='c-'+r.key;
if(hasProp)opt(ch,'yes','Yes',true);opt(ch,'no','No',false);opt(ch,'another','Another page',false);opt(ch,'later','Later',false);
var ed=el('label'),edc=mk('input','checkbox','', 'edit',false);ed.appendChild(edc);ed.appendChild(document.createTextNode('Edit'));ch.appendChild(ed);row.appendChild(ch);
var extra=el('div','qp-extra');row.appendChild(extra);
var pick=el('input');pick.type='text';pick.setAttribute('aria-label','Another page');pick.autocomplete='off';pick.placeholder=kind==='organisation'?'An entity page':'A party, or none';
var dl=el('datalist');dl.id='dl-'+r.key;pick.setAttribute('list',dl.id);
((kind==='organisation'?(bk.picks.entities||[]).map(function(e){return[e.rel,e.title+(e.aliases.length?' ('+e.aliases.join(', ')+')':'')]}):(bk.picks.parties||[]).map(function(p){return[p.tag,p.name]}))).forEach(function(o){var op=el('option');op.value=o[0];op.label=o[1];dl.appendChild(op)});
var oldv=mk('input','text','',r.title,false),newv=mk('input','text','','',false),until=mk('input','date','','',false);
oldv.setAttribute('aria-label','The value as written');newv.setAttribute('aria-label','What it should be');newv.placeholder='What it should be';until.setAttribute('aria-label','Come back on');
[pick,dl,oldv,newv,until].forEach(function(e){extra.appendChild(e)});
function choice(){var c=ch.querySelector('input[type=radio]:checked');return c?c.value:'none'}
function paint(){var c=choice();pick.hidden=c!=='another';until.hidden=c!=='later';oldv.hidden=newv.hidden=!edc.checked;extra.hidden=pick.hidden&&until.hidden&&oldv.hidden;if(out.change)out.change()}
ch.addEventListener('change',paint);
var out={key:r.key,el:row,
action:function(){var c=choice(),e=edc.checked&&oldv.value&&newv.value;if(c==='yes'||c==='another')return'save';if(c==='later')return'later';return e?'save':'none'},
value:function(){var c=choice(),v={do:kind,key:r.key,path:r.path};
if(c==='yes'||c==='another'||c==='later'){v.choice=c;if(c==='another')v.pick=pick.value.trim();if(c==='later')v.until=until.value}
else{v.do='correct';v.choice='yes'}
if(edc.checked&&oldv.value&&newv.value)v.edit={old:oldv.value,new:newv.value};return v}};
paint();return out}
function review(){var box=$('qp-nurture');box.textContent='';rows=[];var v=ubucket(),b=bucket();
var groups=[['Unattributed','whose entity pages are',v.review.entities,v,'answer'],[S.zone,'where people work',b.review.people,b,'organisation']];
groups.forEach(function(g){var items=g[2].filter(function(r){return !S.gone['r:'+r.key]});if(!items.length)return;
var sec=el('div','qp-group');sec.appendChild(el('h3','',g[0]+': '+g[1]+', '+items.length));
items.forEach(function(r){var row=rowFor(r,g[3],g[4]);rows.push(row);sec.appendChild(row.el)});box.appendChild(sec)});
if(b.review.read.length){var d=el('details','qp-group');d.appendChild(el('summary','','Judgment and other findings, to open ('+b.review.read.length+')'));
b.review.read.forEach(function(r){var p=el('div','qp-row');p.appendChild(link(r.path,r.href));p.appendChild(el('div','',r.check));p.appendChild(el('div'));d.appendChild(p)});box.appendChild(d)}
if(!rows.length){box.appendChild(el('div','qp-empty','No findings to answer here.'));return}
var foot=el('div','qp-save'),sv=el('button','act primary qp-hostonly');sv.type='button';
function n(){return rows.filter(function(r){return r.action()==='save'}).length}
function label(){sv.textContent='Save '+n()+' answer'+(n()===1?'':'s')}
rows.forEach(function(r){r.change=label});label();
sv.onclick=function(){var mine=rows.filter(function(r){return r.action()!=='none'});if(!mine.length){say('Nothing to save.');return}
var un=mine.filter(function(r){return r.value().do==='answer'}),pe=mine.filter(function(r){return r.value().do!=='answer'});
if(un.length&&pe.length){say('Save the entity pages and the people one at a time.');return}
var q={verb:'nurture-save',zone:un.length?'unattributed':S.zone,rows:mine.map(function(r){return r.value()})};
if(un.length)q.scope=S.zone;else if(pkey())q.scope=pkey();
act(q,'Saving '+mine.length+' answer'+(mine.length===1?'':'s')+'…')};
foot.appendChild(sv);
var web=el('button','act qp-webonly','Review in the chat');web.type='button';web.setAttribute('data-request','review the context with me');web.setAttribute('data-folder',D.root||'');
foot.appendChild(web);box.appendChild(foot)}
var prevActed=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&q.verb==='nurture-save'){(res&&res.rows||[]).forEach(function(x){var r=rows.filter(function(y){return y.key===x.key})[0];if(!r)return;
if(x.ok){S.gone['r:'+x.key]=1}else{r.el.classList.add('refused');var m=r.el.querySelector('.qp-say');if(!m){m=el('div','qp-say');r.el.appendChild(m)}m.textContent=x.say}});
keep();if(res&&res.ok){var m=rows.filter(function(r){return r.el.classList.contains('refused')});if(!m.length)setTimeout(review,0)}}
if(q&&q.verb==='question-close'&&line.length)drain();
if(prevActed)return prevActed(q,res)};
function all(){bar();counts();list();vlist();work();review();keep()}
$('qp-zone').onchange=function(){S.zone=this.value;S.party='';S.cursor='';all()};
$('qp-party').onchange=function(){S.party=this.value;S.cursor='';all()};
$('qp-source').onchange=function(){S.source=this.value;all()};
$('qp-wiki').onchange=function(){S.wiki=this.value;S.cursor='';all()};
$('qp-age').onchange=function(){S.age=this.value;S.cursor='';all()};
window.GarrickQuestions={open:function(){if(window.StatusTab)StatusTab('questions');window.scrollTo(0,0);var t=root.querySelector('textarea');if(t)t.focus()}};
all()})();
"""
