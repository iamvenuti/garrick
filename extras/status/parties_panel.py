#!/usr/bin/env python3
"""parties_panel.py: the Parties and Who sees what views of the Context tab (#447).

status.py builds the page; this file, beside it, reads the Parties table of
System/context.md and the hubs and thread notes, and draws two of the Context
tab's three views. Parties: one block per zone, with its own party and the
default for new parties in its heading, and under it one row per project with
its parties and their flags; a thread shows only where it names a party its hub
does not. Flip on a party asks page_action.py's `party-flag`, which runs
`scaffold.py party --walled | --open` and commits through the check.
Who sees what: for a project, the parties whose material it may hold and the
projects it may draw from, as labels() and decide() answer them in the
workspace's own garrick_lib; the script only prints that. The Findings view
also gets *Allowed by you*, read from System/walls-allowed.json.

Names, tags and links only: a note's body is never read, only its frontmatter.
Everything is drawn here as escaped text; the script holds the buttons.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

SKIP = {"Inbox", "archive", "_template"}


def _tags(lib, fm: dict) -> List[str]:
    """The parties a note names, `party:` and `parties:` together, in the order written."""
    out: List[str] = []
    for key in ("party", "parties"):
        for t in lib.tag_list(fm.get(key)):
            t = lib.strip_tag(t)
            if t and t not in out:
                out.append(t)
    return out


def _notes(ws: Path, lib) -> List[dict]:
    """Every hub and thread note of every project: {zone, project, thread, path, tags}."""
    out = []
    zones = ws / "Zones"
    if not zones.is_dir():
        return out
    for zone in sorted(p for p in zones.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for project in sorted(p for p in zone.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP):
            hub = project / (project.name + ".md")
            if not hub.is_file():
                continue
            out.append({"zone": zone.name, "project": project.name, "thread": "", "path": hub,
                        "tags": _tags(lib, lib.parse_frontmatter(hub))})
            threads = project / "Threads"
            for t in sorted(p for p in threads.iterdir() if p.is_dir()) if threads.is_dir() else []:
                note = t / (t.name + ".md")
                if note.is_file():
                    out.append({"zone": zone.name, "project": project.name, "thread": t.name, "path": note,
                                "tags": _tags(lib, lib.parse_frontmatter(note))})
    return out


def _href(link: Callable, path: Path) -> str:
    return link.attrs(path) if hasattr(link, "attrs") else 'href="%s"' % html.escape(str(link(path)), quote=True)


def project_id(zone: str, project: str) -> str:
    """The anchor of a project's row: readable, and unique to the zone and the project."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", "%s-%s" % (zone, project)).strip("-").lower()[:40]
    return "cx-p-%s-%s" % (slug, hashlib.sha1(("%s/%s" % (zone, project)).encode("utf-8")).hexdigest()[:6])


def project_ids(data: Optional[dict]) -> set:
    """The anchors a finding may link to."""
    return {p["id"] for z in (data or {}).get("blocks", []) for p in z["projects"]}


LEDGER = ("System", "walls-allowed.json")
LEDGER_MAX = 500


def read_allowed(ws: Path, link: Callable) -> List[dict]:
    """What the user allowed, from System/walls-allowed.json (version 1: path, id, blob, rule, date, by). A missing or
    unreadable ledger, or an entry that does not read, is no allowance: nothing is shown for it. The token a finding
    matched is not in the ledger and not here. `state` says whether the file is still the one that was allowed (its
    git blob id), since an entry matches only on path, id and blob."""
    try:
        data = json.loads(Path(ws).joinpath(*LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
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


def _who(ws: Path, lib, ctx: dict, notes: List[dict]) -> Optional[dict]:
    """Who sees what, read out of the check's own model: labels() gives the parties a project's files carry, decide()
    says what they may hold (write) and may draw from (read). Nothing is decided here. None where the library lacks either."""
    if not all(callable(getattr(lib, n, None)) for n in ("labels", "decide")):
        return None
    cache: dict = {}
    parties = ctx.get("parties") or {}
    order = sorted(parties, key=lambda t: (str(parties[t].get("party") or t).lower(), t))
    hubs = [n for n in notes if not n["thread"]]
    scope_of = {}
    for n in notes:
        try:
            got = lib.labels(ws, n["path"], ctx, cache)
        except Exception:
            got = None
        scope_of[(n["zone"], n["project"], n["thread"])] = got
    hub_tags = {(n["zone"], n["project"]): set(n["tags"]) for n in hubs}
    entries = [n for n in hubs] + [n for n in notes if n["thread"] and set(n["tags"]) - hub_tags.get((n["zone"], n["project"]), set())]
    index = {(n["zone"], n["project"]): i for i, n in enumerate(hubs)}
    out = []
    for n in entries:
        s = scope_of[(n["zone"], n["project"], n["thread"])]
        scope = frozenset(s) if s is not None else frozenset()
        holds = []
        for tag in order:
            verdict = lib.decide(scope, {tag}, "write", ctx)
            if verdict in ("permit", "confirm"):
                holds.append([tag, verdict])
        own = index[(n["zone"], n["project"])]
        draws = []
        for i, h in enumerate(hubs):
            if i == own:
                continue
            theirs = scope_of[(h["zone"], h["project"], "")]
            if lib.decide(scope, theirs, "read", ctx) == "permit":
                draws.append(i)
        zones = []
        for zone in dict.fromkeys(h["zone"] for h in hubs):
            total = [i for i, h in enumerate(hubs) if h["zone"] == zone and i != own]
            got = [i for i in draws if hubs[i]["zone"] == zone]
            if total:
                zones.append({"zone": zone, "total": len(total), "all": len(got) == len(total),
                              "projects": [] if len(got) == len(total) else [hubs[i]["project"] for i in got]})
        note = ""
        if s is None:
            note = "Its notes cannot be read as one set of parties: the hub names none, or two parties with one name meet on a note. It holds nothing until that is fixed."
        out.append({"id": project_id(n["zone"], n["project"]) + ("-" + hashlib.sha1(n["thread"].encode("utf-8")).hexdigest()[:6] if n["thread"] else ""),
                    "zone": n["zone"], "project": n["project"], "thread": n["thread"], "scope": sorted(scope),
                    "holds": holds, "zones": zones, "note": note})
    return {"entries": out, "parties": {t: {"name": parties[t].get("party") or t,
                                            "state": {"yes": "walled", "no": "open"}.get((parties[t].get("flag") or "").strip(), "")}
                                        for t in order}}


def build(ws: Path, lib, link: Callable) -> Optional[dict]:
    """The views' data, or None when the Parties table has no row: no Parties view. `lib` is the workspace's garrick_lib."""
    try:
        ctx = lib.load_context(ws)
        parties = ctx.get("parties") or {}
        if not parties:
            return None
        notes = _notes(ws, lib)
    except Exception:
        return None
    rows: Dict[str, dict] = {}
    for tag, entry in sorted(parties.items(), key=lambda kv: (kv[1].get("party") or kv[0]).lower()):
        flag = (entry.get("flag") or "").strip()
        rows[tag] = {"tag": tag, "name": entry.get("party") or tag, "zone": entry.get("zone") or "", "what": entry.get("what") or "",
                     "state": {"yes": "walled", "no": "open"}.get(flag, ""), "notes": []}
    zone_names = list(ctx.get("zones") or {})
    for n in notes:
        if n["zone"] not in zone_names:
            zone_names.append(n["zone"])
    blocks = {z: {"zone": z, "party": (ctx.get("zone_parties") or {}).get(z, ""),
                  "default": (ctx.get("zone_default") or {}).get(z, "walled"), "projects": [], "unused": []} for z in zone_names}
    nameless, twins = [], []
    by_project: Dict[tuple, dict] = {}
    for n in notes:
        item = {"zone": n["zone"], "project": n["project"], "thread": n["thread"], "href": _href(link, n["path"])}
        if not n["tags"]:
            nameless.append(item)
        for tag in n["tags"]:
            if tag in rows:
                rows[tag]["notes"].append(item)
        for a, b in lib.hats_of(ctx, n["tags"]):
            twins.append(dict(item, tags=[a, b]))
        if not n["thread"]:
            proj = {"id": project_id(n["zone"], n["project"]), "project": n["project"], "href": item["href"], "tags": list(n["tags"]), "threads": []}
            by_project[(n["zone"], n["project"])] = proj
            blocks[n["zone"]]["projects"].append(proj)
    for n in notes:
        if n["thread"]:
            extra = [t for t in n["tags"] if t not in by_project[(n["zone"], n["project"])]["tags"]]
            if extra:       # a thread shows only where it names a party its hub does not
                by_project[(n["zone"], n["project"])]["threads"].append(
                    {"thread": n["thread"], "href": _href(link, n["path"]), "tags": extra})
    unused_other = []
    for r in rows.values():
        if not r["notes"]:
            (blocks[r["zone"]]["unused"] if r["zone"] in blocks else unused_other).append(r["tag"])
    return {"parties": list(rows.values()), "blocks": list(blocks.values()), "nameless": nameless, "twins": twins,
            "unused_other": unused_other, "who": _who(ws, lib, ctx, notes), "allowed": [],
            "dot": any(not r["state"] for r in rows.values()) or bool(twins)}


def counts_of(data: dict) -> dict:
    return {"parties": len(data["parties"]), "walled": sum(r["state"] != "open" for r in data["parties"])}


def dot_title(data: Optional[dict]) -> str:
    """The red dot's title on the Context tab: what in the Parties view needs a look. Nothing when all is well."""
    return "a party has no flag, or a note names two parties with one name" if data and data.get("dot") else ""


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _chip(data: dict, tag: str) -> str:
    """A party on a project row: its name and tag, its flag, and the button that flips it. A tag the Parties table lacks has no button."""
    r = next((x for x in data["parties"] if x["tag"] == tag), None)
    if r is None:
        return '<span class="pp-chip pp-flagless" data-tag="%s"><code>%s</code> <span class="chip pp-none">not in the Parties table</span></span>' % (_e(tag), _e(tag))
    flip = {"walled": "open", "open": "walled"}.get(r["state"], "open")
    return ('<span class="pp-chip%s pp-%s" data-tag="%s"><b>%s</b> <code>%s</code> <span class="chip pp-%s">%s</span>'
            '<button type="button" class="act" data-flip="%s" data-tag="%s" data-name="%s">Make it %s</button></span>' % (
                " pp-flagless" if not r["state"] else "", r["state"] or "none", _e(tag), _e(r["name"]), _e(tag),
                r["state"] or "none", _e(r["state"] or "no flag"), flip, _e(tag), _e(r["name"]), flip))


def _place(item: dict) -> str:
    name = "%s / %s" % (item["project"], item["thread"]) if item["thread"] else item["project"]
    return '<li><a %s>%s</a> <small>%s</small></li>' % (item["href"], _e(name), _e(item["zone"]))


def _by_zone(items: List[dict]) -> str:
    out = []
    for zone in dict.fromkeys(i["zone"] for i in items):
        out.append('<h4>%s</h4><ul>%s</ul>' % (_e(zone), "".join(_place(i) for i in items if i["zone"] == zone)))
    return "".join(out)


def body(data: dict) -> str:
    """The Parties view: one block per zone with its own party and the default for new parties in its heading, one row per
    project with its parties and their flags, then what stands out."""
    out = ['<div class="pp" id="pp">']
    who = bool((data.get("who") or {}).get("entries"))           # the link is there only where the view is
    for z in data["blocks"]:
        if not z["projects"] and not z["unused"] and not z["party"]:
            continue
        own = "<code>%s</code>" % _e(z["party"]) if z["party"] else "no party of its own"
        out.append('<section class="pp-zone" data-zone="%s"><h3>%s <small>%s · new parties %s</small></h3>' % (_e(z["zone"]), _e(z["zone"]), own, _e(z["default"])))
        rows = []
        for p in z["projects"]:
            chips = "".join(_chip(data, t) for t in p["tags"]) or '<span class="chip pp-none">names no party</span>'
            threads = ""
            if p["threads"]:
                threads = ('<details class="pp-threads"><summary>%d thread%s name%s another party</summary><ul>%s</ul></details>' % (
                    len(p["threads"]), "" if len(p["threads"]) == 1 else "s", "s" if len(p["threads"]) == 1 else "",
                    "".join('<li class="pp-trow"><a %s>%s</a> %s</li>' % (t["href"], _e(t["thread"]), "".join(_chip(data, x) for x in t["tags"]))
                            for t in p["threads"])))
            rows.append('<li class="pp-proj" id="%s"><div class="pp-prow"><a %s>%s</a>%s%s</div>%s</li>' % (
                _e(p["id"]), p["href"], _e(p["project"]), chips, ('<a class="pp-who" href="#cx-who" data-who="%s">Who sees what</a>' % _e(p["id"])) if who else "", threads))
        out.append('<ul class="pp-projects">%s</ul>' % "".join(rows) if rows else '<p class="muted">No project here.</p>')
        if z["unused"]:
            out.append('<div class="pp-unused"><h4>Unused</h4><p class="muted">No project or thread names these parties.</p><ul>%s</ul></div>' % "".join(
                '<li class="pp-urow">%s</li>' % _chip(data, t) for t in z["unused"]))
        out.append("</section>")
    if data["unused_other"]:
        out.append('<section class="pp-zone"><h3>Unused <small>parties of no zone listed</small></h3><ul>%s</ul></section>' % "".join(
            '<li class="pp-urow">%s</li>' % _chip(data, t) for t in data["unused_other"]))
    if data["nameless"]:
        out.append('<section class="pp-warn"><h3>Names no party</h3><p class="muted">A note with no party labels nothing, '
                   'and nothing may be written into its project.</p>%s</section>' % _by_zone(data["nameless"]))
    if data["twins"]:
        out.append('<section class="pp-warn"><h3>Names two parties with one name</h3><p class="muted">One company under two hats '
                   'never meets on one note.</p>%s</section>' % _by_zone(data["twins"]))
    out.append("</div>")
    return "".join(out)


def who_body(data: dict) -> str:
    """The Who sees what view: a picker, and the answer the script writes from the data in the page."""
    who = data.get("who")
    if not who or not who["entries"]:
        return ""
    return ('<div class="cxw" id="cxw"><p class="muted">Pick a project to see which parties\' material it may hold and which zones and projects it may '
            'draw from. This is the wall check\'s own answer, read out; the page works nothing out for itself.</p>'
            '<label>Project <select id="cxw-pick"></select></label><div id="cxw-out" aria-live="polite"></div></div>'
            '<script type="application/json" id="cxw-data">%s</script>' % _json(who))


def allowed_body(data: dict) -> str:
    """Allowed by you: each allowance with its file, rule, date and Remove, or nothing where there is none."""
    rows = data.get("allowed") or []
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
    return ('<section class="cxa" id="cxa"><h3>Allowed by you</h3><p class="muted">A finding you chose to let through, once, for the file as it was. '
            'Editing the file ends the allowance. Remove puts the refusal back.</p><ul>%s</ul></section>' % "".join(items))


VIEWS = (("findings", "Findings"), ("parties", "Parties"), ("who", "Who sees what"))


def tab(findings: str, data: Optional[dict]) -> str:
    """The Context tab's inside. `findings` is what the tab showed before (the questions panel and the cards under it, or
    nothing). With no Parties table the tab is that, unchanged; with one it has three views under one Show switch."""
    if not data:
        return findings
    allowed = allowed_body(data)
    parts = {"findings": findings + allowed if (findings or allowed) else "", "parties": body(data), "who": who_body(data)}
    have = [(k, t) for k, t in VIEWS if parts[k]]
    first = have[0][0]
    bar = ""
    if len(have) > 1:
        bar = ('<div class="cx-bar"><span>Show</span><div class="cx-switch" id="cx-switch" role="group" aria-label="Show">%s</div></div>' % "".join(
            '<button type="button" data-view="%s" aria-pressed="%s">%s</button>' % (k, "true" if k == first else "false", t) for k, t in have))
    return '<div class="cx" id="cx">%s%s</div>' % (bar, "".join(
        '<div class="cx-view" id="cx-%s" data-cx-view="%s"%s>%s</div>' % (k, k, "" if k == first else " hidden", parts[k]) for k, _ in have))


CSS = r"""
/* the Parties and Who sees what views of the Context tab (#447) */
.cx-bar{display:flex;align-items:center;gap:8px;margin:0 0 14px;font-size:13px;color:var(--ink2)}
.cx-switch{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.cx-switch button{font:inherit;font-size:13px;color:var(--ink2);background:var(--surface);border:0;padding:4px 12px;cursor:pointer}
.cx-switch button+button{border-left:1px solid var(--line)}
.cx-switch button[aria-pressed=true]{color:var(--ink);background:var(--raise);box-shadow:inset 0 -2px 0 var(--accent)}
.cx-view[hidden]{display:none}
.pp-zone{border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:10px 14px;margin:0 0 12px}
.pp-zone h3{margin:0 0 8px;font:600 16px/1.3 var(--display)}.pp-zone h3 small{font:400 12px var(--body,inherit);color:var(--muted);margin-left:8px}
.pp-zone h4,.pp-warn h4{margin:8px 0 4px;font-size:13px}
.pp-projects,.pp-unused ul{list-style:none;margin:0;padding:0}
.pp-proj,.pp-urow{padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.pp-prow{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}.pp-prow>a:first-child{font-weight:600}.pp-who{margin-left:auto;font-size:12px}
.pp-chip{display:inline-flex;flex-wrap:wrap;gap:6px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:2px 8px}
.pp-flagless{border-color:var(--critical)}.pp-none{color:var(--warning)}.pp-walled{background:var(--raise)}.pp-open{box-shadow:inset 0 0 0 1px var(--good)}
.pp-threads{margin:6px 0 0 12px}.pp-threads ul{list-style:none;margin:4px 0 0;padding:0}.pp-trow{padding:3px 0}
.pp-ask{flex-basis:100%;margin:8px 0 0;padding:8px 12px;border:1px solid var(--warning);border-radius:8px}.pp-ask p{margin:0 0 8px}.pp-ask-opts{display:flex;gap:8px}
.pp-warn{border:1px solid var(--warning);border-radius:10px;padding:10px 14px;margin:0 0 10px}.pp-warn h3{margin:0 0 4px;font-size:15px}
.pp-warn ul{margin:4px 0 0;padding-left:18px;font-size:13px}
.cxw label{display:flex;gap:8px;align-items:center;font-size:13px;margin:0 0 12px}
.cxw select{font:inherit;font-size:13px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 8px}
#cxw-out h3{margin:0 0 6px;font:600 16px/1.3 var(--display)}#cxw-out h4{margin:12px 0 4px;font-size:13px}#cxw-out ul{margin:0;padding-left:18px;font-size:13px}
.pp-warnline{color:var(--warning);font-size:13px}
.cxa{border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:10px 14px;margin:14px 0 0}.cxa h3{margin:0 0 4px;font-size:15px}
.cxa ul{list-style:none;margin:8px 0 0;padding:0}.cxa-row{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.cxa-row .muted{grid-column:1}.cxa-row .act{grid-column:2;grid-row:1/3;align-self:center}
"""

JS = r"""
(function(){var root=document.getElementById('pp');if(!root)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function say(s){if(window.GarrickSay)GarrickSay(s)}
function send(q,said){if(!host){var w='run scaffold.py party --tag '+q.tag+' --'+q.flag+(q.yes?' --yes':'');
if(window.GarrickCopy)GarrickCopy(w).then(function(){say('A browser cannot change anything. Copied: '+w)});else say('Answer this in the Garrick app: '+w);return}
if(!(window.GarrickAct&&GarrickAct(q,said)))host.postMessage({act:q});say(said)}
var lastRow=null;
root.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-flip]');if(!b)return;lastRow=b.closest('li');
send({verb:'party-flag',tag:b.dataset.tag,flag:b.dataset.flip},'Making '+b.dataset.name+' '+b.dataset.flip+'…')});
/* the command says what a walled-to-open change releases and writes nothing until it is told yes: the panel asks inline
(a web view shows no browser dialog), and only its button sends the request again with yes */
function drop(){var o=root.querySelector('.pp-ask');if(o)o.remove()}
function ask(q,out){drop();var card=lastRow||root.querySelector('[data-tag="'+q.tag+'"]');if(!card)return;
var box=document.createElement('div');box.className='pp-ask';box.setAttribute('role','group');
var t=document.createElement('p');t.textContent=out.say;box.appendChild(t);
var row=document.createElement('div');row.className='pp-ask-opts';
var go=document.createElement('button');go.type='button';go.className='act primary';go.textContent='Make it '+q.flag;
var no=document.createElement('button');no.type='button';no.className='act';no.textContent='Cancel';
go.onclick=function(){drop();send(Object.assign({},q,{yes:true}),'Making '+q.tag+' '+q.flag+'…')};no.onclick=drop;
row.appendChild(go);row.appendChild(no);box.appendChild(row);card.appendChild(box);go.focus()}
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&q.verb==='party-flag'&&out&&out.ok&&out.ask&&!q.yes){ask(q,out);return}
if(prev)return prev(q,out)}})();
"""

CX_JS = r"""
(function(){var cx=document.getElementById('cx');if(!cx)return;
var K='garrick-context-view',host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);sessionStorage.setItem(k,v)}catch(e){return null}}
function say(s){if(window.GarrickSay)GarrickSay(s)}
function el(t,c,x){var e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e}
var views=[].map.call(cx.querySelectorAll('[data-cx-view]'),function(v){return v.getAttribute('data-cx-view')});
/* the switch: one view of the Context tab at a time, remembered in this window */
function show(n){if(views.indexOf(n)<0)n=views[0];
cx.querySelectorAll('[data-cx-view]').forEach(function(v){v.hidden=v.getAttribute('data-cx-view')!==n});
cx.querySelectorAll('#cx-switch button').forEach(function(b){b.setAttribute('aria-pressed',b.getAttribute('data-view')===n?'true':'false')});ss(K,n)}
cx.querySelectorAll('#cx-switch button').forEach(function(b){b.onclick=function(){show(b.getAttribute('data-view'))}});
window.GarrickContextView=show;
window.GarrickCxFor=function(e){var v=e&&e.closest&&e.closest('[data-cx-view]');if(v)show(v.getAttribute('data-cx-view'))};
var want=window.GarrickCxWant||ss(K);window.GarrickCxWant=null;show(want||views[0]);
var qo=window.GarrickQuestions;if(qo&&qo.open){var o=qo.open;qo.open=function(){show('findings');o()}}
/* who sees what: the data was worked out by the wall check's own functions; this only prints it */
var dEl=document.getElementById('cxw-data'),pick=document.getElementById('cxw-pick'),out=document.getElementById('cxw-out'),W=null;
try{W=dEl&&JSON.parse(dEl.textContent)}catch(e){}
function name(x){return x.project+(x.thread?' / '+x.thread:'')}
function draw(id){var x=W.entries.filter(function(y){return y.id===id})[0]||W.entries[0];pick.value=x.id;out.textContent='';
out.appendChild(el('h3','',name(x)));if(x.note)out.appendChild(el('p','pp-warnline',x.note));
out.appendChild(el('h4','','Its parties'));out.appendChild(el('p','',x.scope.length?x.scope.join(', '):'none'));
out.appendChild(el('h4','','May hold material of'));
if(!x.holds.length)out.appendChild(el('p','muted','No party.'));
else{var ul=el('ul');x.holds.forEach(function(h){var p=W.parties[h[0]]||{name:h[0],state:''},li=el('li','',p.name+' ');
li.appendChild(el('code','',h[0]));li.appendChild(document.createTextNode(' '));li.appendChild(el('span','chip pp-'+(p.state||'none'),p.state||'no flag'));
if(h[1]==='confirm')li.appendChild(el('small','',' asked first'));ul.appendChild(li)});out.appendChild(ul)}
out.appendChild(el('h4','','May draw from'));
if(!x.zones.length)out.appendChild(el('p','muted','No other project.'));
else{var zl=el('ul');x.zones.forEach(function(z){zl.appendChild(el('li','',z.zone+': '+(z.all?'every other project ('+z.total+')':z.projects.length?z.projects.join(', ')+' ('+z.projects.length+' of '+z.total+')':'none of '+z.total+' projects')))});out.appendChild(zl)}}
if(W&&W.entries&&W.entries.length&&pick&&out){var zs=[];W.entries.forEach(function(x){if(zs.indexOf(x.zone)<0)zs.push(x.zone)});
zs.forEach(function(z){var g=el('optgroup');g.label=z;W.entries.forEach(function(x){if(x.zone===z){var o=el('option','',name(x));o.value=x.id;g.appendChild(o)}});pick.appendChild(g)});
pick.onchange=function(){ss('garrick-context-who',pick.value);draw(pick.value)};draw(ss('garrick-context-who')||W.entries[0].id);
cx.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('[data-who]');if(!a)return;show('who');draw(a.getAttribute('data-who'))})}
/* Allowed by you: Remove puts the refusal back, through the page's walls-unallow */
cx.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-unallow]');if(!b)return;var r=b.closest('.cxa-row');if(!r)return;
var q={verb:'walls-unallow',path:r.getAttribute('data-path'),id:r.getAttribute('data-id')};
if(!host){say('A browser cannot change anything. Remove it in the Garrick app.');return}
if(!(window.GarrickAct&&GarrickAct(q,'Removing…')))host.postMessage({act:q});say('Removing…')});
var prev=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&q.verb==='walls-unallow'&&res&&res.ok){[].forEach.call(cx.querySelectorAll('.cxa-row'),function(r){if(r.getAttribute('data-path')===q.path&&r.getAttribute('data-id')===q.id)r.remove()})}
if(prev)return prev(q,res)}})();
"""
