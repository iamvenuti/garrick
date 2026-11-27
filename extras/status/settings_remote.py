#!/usr/bin/env python3
"""settings_remote.py: Settings › Remote access (preview): the markup, the style and the script (#695, #697, #698, #696).

`status.py` loads this beside `settings_guard.py` and draws what `System/tools/view_settings.py` read through the extra's own `state.py`
(`view_settings.remote()`): this module reads nothing and writes nothing. Each button sends the page-only verb `remote` with an `action`
(`enable`, `pause`, `resume`, `off`, `pair`, `zone`, `revoke`), and the verb runs `System/remote/settings_actions.py` at the Mac.

The section says **Preview** under its heading. Its words are plain: no path, key or command outside the *Details* fold. The notice that
comes before a walled zone is turned on is the extra's own `notice.md`, with the zone's name put in. The buttons work in Garrick.app only;
a browser shows the state and says so.

Standard library only.
"""
from __future__ import annotations

import html as _html
from typing import Callable, Dict, List

E = _html.escape

LEDE = "Preview. Lets an assistant on your phone work with this workspace, when you allow it."
HELP = ("Nothing is served until you turn this on. Anything an assistant reads leaves this computer, and you set what each one may reach.")
STATES = {"off": "Off", "on": "On", "paused": "Paused"}
NOT_BROWSER = "Remote access is changed in Garrick.app."


ADD_REQUEST = ("copy the folder extras/remote of my Garrick download to System/remote in this workspace, leave out its tests folder, "
               "and tell me when it is done")


def _classes(c: List[str]) -> str:
    return "can read and write" if "write" in c else "can read"


def _steps(steps: List[dict]) -> str:
    items = "".join('<li data-step="%s" data-done="%s"><span class="rstep">%s</span> %s%s</li>'
                    % (E(s["key"]), "true" if s["done"] else "false", "Done" if s["done"] else "To do", E(s["text"]),
                       ' <small>%s</small>' % E(s["note"]) if s.get("note") else "") for s in steps)
    return '<ol class="remotesteps" id="remote-steps">%s</ol>' % items


def _reach(g: dict, notice: str) -> str:
    rows = ""
    for z in g.get("reach") or []:
        if not z["walled"]:
            rows += ('<li class="rreach open" data-zone="%s"><b>%s</b> <span class="st idle">Open</span> <small>%s</small></li>'
                     % (E(z["zone"]), E(z["zone"]), "Always in reach: reads%s" % (" and writes" if "write" in g["classes"] else "")))
            continue
        since = ' <small>On since %s</small>' % E(z["since"]) if z["since"] else ""
        rows += ('<li class="rreach walled" data-zone="%s" data-grant="%s"><b>%s</b> <span class="st good">Walled</span>'
                 '<label class="rchk"><input type="checkbox" data-rr="read"%s> Read</label>'
                 '<label class="rchk"><input type="checkbox" data-rr="write"%s%s> Write</label>%s'
                 '<p class="hint rnotice" hidden>%s</p></li>'
                 % (E(z["zone"]), E(g["id"]), E(z["zone"]), " checked" if z["read"] else "", " checked" if z["write"] else "",
                    "" if "write" in g["classes"] else " disabled", since, E(notice.replace("{zone}", z["zone"]))))
    why = '<p class="hint bad rwhy">%s</p>' % E(g["reach_note"]) if g.get("reach_note") else ""
    return ('<details class="rreachbox"><summary>What it may reach</summary>%s<p class="hint">Walled zones are off until you turn them on '
            'here, by name. Reads and writes are separate choices. A zone that was turned on before this version, or that was removed and made '
            'again, stays off until you turn it on here again.</p><ul class="rreaches">%s</ul>'
            '<div class="rconfirm" hidden><button class="act sm" type="button" data-rconfirm="1">Turn on</button> '
            '<button class="act sm" type="button" data-rcancel="1">Cancel</button></div></details>' % (why, rows))


def _grants(rows: List[dict], notice: str) -> str:
    if not rows:
        return '<p class="hint" id="remote-nogrants">No assistant is connected yet.</p>'
    items = ""
    for g in rows:
        items += ('<li class="rgrant" data-grant="%s"><div class="rgline"><b>%s</b> <small>%s. Connected %s%s.</small> '
                  '<button class="act sm apponly rrevoke" type="button" data-revoke="%s">Revoke</button></div>%s</li>'
                  % (E(g["id"]), E(g["name"]), _classes(g["classes"]), E(g["created"]),
                     ", last used %s" % E(g["last_used"]) if g["last_used"] else ", not used yet", E(g["id"]), _reach(g, notice)))
    return '<ul class="rgrants" id="remote-grants">%s</ul>' % items


REQUEST_NONE = "No sign-in was waiting when this page was last refreshed. Start one in your assistant, then choose Show a code."


def _requests(rows: List[dict], coded: str) -> str:
    """The sign-in requests that wait for the owner: the name each client gave and when it started. A code is made for the one picked; with
    one waiting it is picked already. Names come from the client, so they are escaped here and shown as text only."""
    if not rows:
        return '<div class="rrequests" id="remote-requests"><p class="hint" id="remote-norequests">%s</p></div>' % E(REQUEST_NONE)
    many = len(rows) > 1
    items = ""
    for i, r in enumerate(rows):
        label = '<b>%s</b> <small>Sign-in %s. Started %s.</small>' % (E(r["name"]), E(r["id"]), E(r["started"]))
        pick = ('<input type="radio" name="remote-request" value="%s"%s> ' % (E(r["id"]), " checked" if r["id"] == coded else "")) if many else ""
        items += '<li class="rreq" data-request="%s"><label class="rchk">%s%s</label></li>' % (E(r["id"]), pick, label)
    ask = ("Pick the sign-in you started, then choose Show a code." if many else "Choose Show a code for this sign-in.") \
        + " The sign-in number must match the one on the sign-in page. This list is as of the last refresh."
    return ('<div class="rrequests" id="remote-requests"><p class="hint">%s</p><ul class="rreqs" id="remote-reqlist">%s</ul></div>'
            % (E(ask), items))


def section(v: dict, h: Dict[str, Callable], workspace: str) -> str:
    """The whole section for one document of `view_settings.remote()`. `h` holds the page's own helpers: set_head, help_button, help_text,
    request_button."""
    head = h["set_head"]("Remote access", "remote", LEDE)
    tail = h["help_text"]("remote", E(HELP))
    row = h["set_row"]
    label = h["row_label"]
    if not v.get("installed"):
        ask = h["request_button"]("Ask my assistant to add it", ADD_REQUEST, workspace, "act sm")
        body = (row(label("Remote access", "Not installed. Your assistant can add it."),
                    '<span class="st idle" id="remote-missing">Not installed</span> ' + ask)
                + '<details class="rdetails" id="remote-how"><summary>Details</summary><p class="rnote">To add it, ask your assistant to copy remote access '
                  'from your Garrick download into this workspace: the folder extras/remote goes to System/remote, without its tests folder. '
                  'Then reopen Settings. Updating Garrick then keeps it current.</p></details>')
        return '<section class="setsec" id="remote-settings" data-state="missing">%s%s%s</section>' % (head, tail, body)
    state = v["status"]
    if v.get("refusal"):
        body = row(label("Remote access", E(v["refusal"]), "", "remote-refused"), '<span class="st idle">Cannot be turned on</span>')
        return '<section class="setsec" id="remote-settings" data-state="refused">%s%s%s</section>' % (head, tail, body)
    addr = v["address"]
    own = addr.get("adapter") == "own"
    address = ('<p class="raddr" id="remote-address">Your address: <b>%s</b></p>' % E(addr["url"])) if addr.get("url") else ""
    pairing = v.get("pairing") or {}
    waiting = '<p class="hint" id="remote-waiting">A code is waiting.</p>' if pairing.get("waiting") else ""
    locked = ('<p class="hint bad" id="remote-locked">Many wrong codes were tried. A sign-in with no code made for it takes none for a while. Show a code still works.</p>'
              if pairing.get("locked") else "")
    setup = ('<div class="rsetup r-off" id="remote-setup"><label class="rlabel">How will your assistant reach this Mac?'
             '<select id="remote-adapter" class="menu-style"><option value="relay"%s>Through a relay</option>'
             '<option value="own"%s>Through an address I already have</option></select></label>'
             '<label class="rlabel" id="remote-own" hidden>Your address <input type="text" id="remote-url" autocomplete="off" '
             'placeholder="https://mcp.your-name.example" value="%s"></label></div>'
             % ("" if own else " selected", " selected" if own else "", E(addr["url"] if own else "")))
    buttons = ('<div class="rbtns apponly">'
               '<button class="act sm r-off" type="button" data-raction="enable">Turn on</button>'
               '<button class="act sm r-on" type="button" data-raction="enable" data-again="1">Check the address again</button>'
               '<button class="act sm r-on" type="button" data-raction="pause">Pause</button>'
               '<button class="act sm r-paused" type="button" data-raction="resume">Resume</button>'
               '<button class="act sm r-on" type="button" data-raction="pair">Show a code</button>'
               '<button class="act sm r-on r-paused" type="button" data-raction="off">Turn off</button></div>'
               '<p class="hint nohost-only">%s</p>' % NOT_BROWSER)
    details = ('<details class="rdetails"><summary>Details</summary><p class="hint">The service listens on this computer only, on port %d. '
               'The relay or your own address carries the traffic to it.</p></details>' % int(v["port"]))
    pill = row(label("Remote access", "Preview"), '<span class="st %s" id="remote-pill">%s</span>' % ("good" if state == "on" else "idle", STATES[state]))
    asking = _requests(v["requests"], str(pairing.get("request") or "")) if "requests" in v else ""      # an older extra has no list: none is drawn
    code = ('<p class="rcode" id="remote-code" aria-live="polite" hidden>Your code: <b class="rdigits"></b> '
            '<small>It works once, for five minutes.</small></p>')
    return ('<section class="setsec" id="remote-settings" data-state="%s" data-notice="%s">%s%s%s%s%s%s%s%s%s%s%s%s%s'
            '<p class="hint rsaid" id="remote-said" aria-live="polite" hidden></p></section>'
            % (E(state), E(v.get("notice") or ""), head, tail, pill, setup, address, asking, buttons, code, waiting, locked, _steps(v["steps"]),
               _grants(v["grants"], v.get("notice") or ""), details))


CSS = r"""
/* Settings › Remote access (preview) */
#remote-settings .rstate{margin:.2rem 0}#remote-settings .rsetup{display:grid;gap:8px;margin:.5rem 0}
#remote-settings .rbtns{display:flex;flex-wrap:wrap;gap:8px;margin:.5rem 0}
#remote-settings .remotesteps{list-style:none;margin:.5rem 0;padding:0;display:grid;gap:4px;font-size:var(--fs-meta)}
#remote-settings .rstep{display:inline-block;min-width:3.2em;color:var(--muted)}
#remote-settings [data-done="true"] .rstep{color:var(--ink)}
#remote-settings .rgrants,#remote-settings .rreaches{list-style:none;margin:.4rem 0;padding:0;display:grid;gap:6px}
#remote-settings .rgrant{padding:8px 10px;border:1px solid var(--line);border-radius:10px}
#remote-settings .rgline{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
#remote-settings .rchk{margin-left:12px;font-size:var(--fs-meta)}
#remote-settings .rdigits{font-size:var(--fs-h3);letter-spacing:.25em}
#remote-settings .rsaid.bad{color:var(--bad,#b00)}
#remote-settings .r-off,#remote-settings .r-on,#remote-settings .r-paused{display:none}
#remote-settings[data-state="off"] button.r-off,#remote-settings[data-state="on"] button.r-on,
#remote-settings[data-state="paused"] button.r-paused{display:inline-block}
#remote-settings[data-state="off"] .rsetup.r-off{display:grid}
#remote-settings .rbtns button[hidden]{display:none}
#remote-settings .rrequests{display:none;margin:.5rem 0}
#remote-settings[data-state="on"] .rrequests{display:block}
#remote-settings .rreqs{list-style:none;margin:.3rem 0;padding:0;display:grid;gap:4px}
#remote-settings .rreq .rchk{margin-left:0;display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
"""

JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,sec=document.getElementById('remote-settings');
if(!sec||!sec.dataset.state||sec.dataset.state==='missing'||sec.dataset.state==='refused')return;
var said=document.getElementById('remote-said'),pending=null,tick=null;
function tell(t,bad,code){if(!said)return;said.hidden=false;said.className='hint rsaid'+(bad?' bad':'');
if(window.GarrickFailClear)GarrickFailClear(said);
if(bad&&window.GarrickFail){said.textContent='';GarrickFail(said,code||'remote',String(t||''));return}
said.textContent=String(t||'')}
function send(q){if(!host||pending)return false;pending=q;host.postMessage({act:q});return true}
var ad=document.getElementById('remote-adapter'),own=document.getElementById('remote-own'),url=document.getElementById('remote-url');
function adapter(){if(own)own.hidden=!ad||ad.value!=='own'}
if(ad){ad.onchange=adapter;adapter()}
function setState(s){sec.dataset.state=s;var p=document.getElementById('remote-pill');if(p){p.textContent={off:'Off',on:'On',paused:'Paused'}[s];p.className='st '+(s==='on'?'good':'idle')}}
function showCode(code,secs){var box=document.getElementById('remote-code');if(!box)return;box.hidden=false;box.querySelector('.rdigits').textContent=code;
var left=secs||300;clearInterval(tick);tick=setInterval(function(){left--;if(left<=0){clearInterval(tick);box.hidden=true;box.querySelector('.rdigits').textContent=''}},1000)}
var awaiting=null;
sec.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
if(b.dataset.raction){var q={verb:'remote',action:b.dataset.raction};
if(q.action==='pair'&&sec.querySelector('#remote-requests')){var pick=sec.querySelector('input[name=remote-request]:checked'),one=sec.querySelectorAll('#remote-reqlist .rreq');
if(pick)q.request=pick.value;else if(one.length===1)q.request=one[0].dataset.request}
if(q.action==='enable'){q.adapter=ad?ad.value:'relay';if(q.adapter==='own')q.address=url?url.value.trim():''}
send(q);return}
if(b.dataset.revoke){send({verb:'remote',action:'revoke',grant:b.dataset.revoke});return}
if(b.dataset.rconfirm&&awaiting){var li=awaiting.li;send({verb:'remote',action:'zone',grant:li.dataset.grant,zone:li.dataset.zone,
read:li.querySelector('[data-rr=read]').checked,write:li.querySelector('[data-rr=write]').checked,acknowledged:true});return}
if(b.dataset.rcancel&&awaiting){awaiting.box.checked=!awaiting.box.checked;closeNotice();return}});
function closeNotice(){if(awaiting){awaiting.li.querySelector('.rnotice').hidden=true;awaiting=null}
sec.querySelectorAll('.rconfirm').forEach(function(c){c.hidden=true})}
sec.addEventListener('change',function(e){var i=e.target;if(!i.matches('[data-rr]'))return;var li=i.closest('.rreach');if(!li)return;
if(awaiting)closeNotice();
if(i.checked){awaiting={li:li,box:i};li.querySelector('.rnotice').hidden=false;var c=li.closest('.rreachbox').querySelector('.rconfirm');li.appendChild(c);c.hidden=false;return}
send({verb:'remote',action:'zone',grant:li.dataset.grant,zone:li.dataset.zone,read:li.querySelector('[data-rr=read]').checked,
write:li.querySelector('[data-rr=write]').checked,acknowledged:false})});
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&q.verb==='remote'){pending=null;var none=!out,odd=!none&&/^(unknown|lost|crashed)$/.test(String((out.plain&&out.plain.code)||out.outcome||''));
out=out||{ok:false,say:'That did not work.'};tell(out.say,!out.ok,none?'lost':odd?'unknown':'remote');
if(out.ok){var a=q.action;if(a==='enable'||a==='resume')setState('on');else if(a==='pause')setState('paused');else if(a==='off')setState('off');
else if(a==='pair'&&out.code)showCode(out.code,out.seconds);
else if(a==='revoke'){var g=sec.querySelector('.rgrant[data-grant="'+q.grant+'"]');if(g)g.remove()}
else if(a==='zone')closeNotice()}
else if(q.action==='zone'&&awaiting){awaiting.box.checked=!awaiting.box.checked;closeNotice()}
return}
if(prev)return prev(q,out)};
})();
"""
