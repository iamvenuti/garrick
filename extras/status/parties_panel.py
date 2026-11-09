#!/usr/bin/env python3
"""parties_panel.py: the Parties tab's data and page (#447).

status.py builds the page; this file, beside it, reads the Parties table of
System/context.md and the hubs and thread notes, and draws the tab: each party
with its flag (walled or open) and the projects and threads that name it, the
zones' own party and default above. It shows flags and who names whom, and that
is the whole model. Flip on a row asks page_action.py's `party-flag`, which runs
`scaffold.py party --walled | --open` and commits through the check.

Names, tags and links only: a note's body is never read, only its frontmatter.
Everything is drawn here as escaped text; the script holds the one button.

Standard library only, Python 3.9.
"""

from __future__ import annotations

import html
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


def build(ws: Path, lib, link: Callable) -> Optional[dict]:
    """The tab's data, or None when the Parties table has no row: no tab. `lib` is the workspace's garrick_lib."""
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
    nameless, twins = [], []
    for n in notes:
        item = {"zone": n["zone"], "project": n["project"], "thread": n["thread"], "href": link.attrs(n["path"]) if hasattr(link, "attrs")
                else 'href="%s"' % html.escape(str(link(n["path"])), quote=True)}
        if not n["tags"]:
            nameless.append(item)
        for tag in n["tags"]:
            if tag in rows:
                rows[tag]["notes"].append(item)
        for a, b in lib.hats_of(ctx, n["tags"]):
            twins.append(dict(item, tags=[a, b]))
    zones = [{"zone": z, "party": (ctx.get("zone_parties") or {}).get(z, ""),
              "default": (ctx.get("zone_default") or {}).get(z, "walled")} for z in ctx.get("zones") or {}]
    return {"parties": list(rows.values()), "zones": zones, "nameless": nameless, "twins": twins,
            "dot": any(not r["state"] for r in rows.values()) or bool(twins)}


def counts_of(data: dict) -> dict:
    return {"parties": len(data["parties"]), "walled": sum(r["state"] != "open" for r in data["parties"])}


def tab_button(data: dict) -> str:
    dot = '<span class="dot critical" title="%s"></span>' % (
        "a party has no flag, or a note names two parties with one name" if data.get("dot") else "")
    return '<button type="button" role="tab" data-tab="parties">Parties%s</button>' % (dot if data.get("dot") else "")


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _place(item: dict) -> str:
    name = "%s / %s" % (item["project"], item["thread"]) if item["thread"] else item["project"]
    return '<li><a %s>%s</a> <small>%s</small></li>' % (item["href"], _e(name), _e(item["zone"]))


def body(data: dict) -> str:
    """The tab's page: the zones, then one article per party, then what stands out."""
    zones = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        _e(z["zone"]), "<code>%s</code>" % _e(z["party"]) if z["party"] else '<span class="muted">none</span>', _e(z["default"]))
        for z in data["zones"])
    out = ['<div class="pp" id="pp">']
    if zones:
        out.append('<table class="pp-zones"><caption>Zones</caption><thead><tr><th>Zone</th><th>Its party</th><th>New parties</th></tr>'
                   '</thead><tbody>%s</tbody></table>' % zones)
    for r in data["parties"]:
        state = r["state"] or "no flag"
        flip = {"walled": "open", "open": "walled"}.get(r["state"], "open")
        shown = ('<ul>%s</ul>' % "".join(_place(i) for i in r["notes"])) if r["notes"] else \
            '<p class="pp-none">No project or thread names this party.</p>'
        out.append(
            '<article class="pp-party%s" data-tag="%s"><header><b>%s</b> <code>%s</code> <span class="chip pp-%s">%s</span> '
            '<small>%s</small><button type="button" class="act" data-flip="%s" data-tag="%s" data-name="%s">Make it %s</button></header>'
            '<p class="muted">%s</p>%s</article>' % (
                " pp-flagless" if not r["state"] else "", _e(r["tag"]), _e(r["name"]), _e(r["tag"]),
                (r["state"] or "none"), _e(state), _e(r["zone"]), flip, _e(r["tag"]), _e(r["name"]), flip,
                _e(r["what"]), shown))
    if data["nameless"]:
        out.append('<section class="pp-warn"><h3>Names no party</h3><p class="muted">A note with no party labels nothing, '
                   'and nothing may be written into its project.</p><ul>%s</ul></section>' % "".join(_place(i) for i in data["nameless"]))
    if data["twins"]:
        out.append('<section class="pp-warn"><h3>Names two parties with one name</h3><p class="muted">One company under two hats '
                   'never meets on one note.</p><ul>%s</ul></section>' % "".join(_place(i) for i in data["twins"]))
    out.append("</div>")
    return "".join(out)


CSS = r"""
/* the Parties tab (#447) */
.pp table{border-collapse:collapse;margin:0 0 18px;font-size:13px}.pp caption{text-align:left;font-weight:600;padding:0 0 6px}
.pp th,.pp td{text-align:left;padding:4px 18px 4px 0;border-bottom:1px solid var(--line)}
.pp-party{border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:10px 14px;margin:0 0 10px}
.pp-party header{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}.pp-party header .act{margin-left:auto}
.pp-party ul,.pp-warn ul{margin:6px 0 0;padding-left:18px;font-size:13px}.pp-party p{margin:6px 0 0;font-size:13px}
.pp-flagless{border-color:var(--critical)}.pp-none{color:var(--warning)}.pp-walled{background:var(--raise)}.pp-open{box-shadow:inset 0 0 0 1px var(--good)}
.pp-ask{margin:8px 0 0;padding:8px 12px;border:1px solid var(--warning);border-radius:8px}.pp-ask p{margin:0 0 8px}.pp-ask-opts{display:flex;gap:8px}
.pp-warn{border:1px solid var(--warning);border-radius:10px;padding:10px 14px;margin:0 0 10px}.pp-warn h3{margin:0 0 4px;font-size:15px}
"""

JS = r"""
(function(){var root=document.getElementById('pp');if(!root)return;
var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick;
function say(s){if(window.GarrickSay)GarrickSay(s)}
function send(q,said){if(!host){var w='run scaffold.py party --tag '+q.tag+' --'+q.flag+(q.yes?' --yes':'');
if(window.GarrickCopy)GarrickCopy(w).then(function(){say('A browser cannot change anything. Copied: '+w)});else say('Answer this in the Garrick app: '+w);return}
if(!(window.GarrickAct&&GarrickAct(q,said)))host.postMessage({act:q});say(said)}
root.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-flip]');if(!b)return;
send({verb:'party-flag',tag:b.dataset.tag,flag:b.dataset.flip},'Making '+b.dataset.name+' '+b.dataset.flip+'…')});
/* the command says what a walled-to-open change releases and writes nothing until it is told yes: the panel asks inline
(a web view shows no browser dialog), and only its button sends the request again with yes */
function drop(){var o=root.querySelector('.pp-ask');if(o)o.remove()}
function ask(q,out){drop();var card=root.querySelector('[data-tag="'+q.tag+'"]');if(!card)return;
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
