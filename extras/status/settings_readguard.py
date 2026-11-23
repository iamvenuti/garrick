#!/usr/bin/env python3
"""settings_readguard.py: Settings > Walls > Read guard and Settings > About > This computer, as the grid draws them (#673, #674, #682).

settings_guard.py keeps what the read guard is and what its log holds: the hook folders it trusts, the log's lines, `read_state()`.
This file only draws, from what those give: one part of Walls for the read guard with one sub-heading and one "?", the three choices
each with what it does, a list that names each file and its zone, *Across a wall* only under On, the connected services by name under a
closed fold of their own under Watch and On (#683), and the machine's row in the page's grid. No pattern and no tool name is drawn. It
reads and writes nothing. Every function takes the settings_guard module as `sg`, for its words.
Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Callable, Dict, List, Optional

MODES = (("off", "Off"), ("warn", "Watch"), ("enforce", "On"))
# What each choice does for the person whose material it protects (#674); how it is installed is behind the "?".
MODE_SAID = {"off": "Nothing is checked when the assistant reads.",
             "warn": "Nothing is stopped. For a week, you see what would have been.",
             "enforce": "Reads behind another wall are stopped."}
PROTECTS = "The assistant does not read what sits behind the wall of another zone."
# The texts of #681: one short "?" for the read guard, one for the connected tools, one for this computer.
HELP_TEXT = ("Walls stop your assistant from writing across zones. The read guard stops it from reading across zones. Start with "
             "Watch for a week, then choose On.")
TOOLS_TEXT = ("A mail or calendar search can return messages from every zone. Garrick takes out what sits behind another wall "
              "before your assistant sees it.")
MACHINE_TEXT = "Change this only if a second computer keeps a copy of your workspace."
CODEX_TRUST = "Codex runs the read guard only after you trust it in Codex's own settings, and again after each change you make here."
# Across a wall shows under On only, and each choice says what it does (#683).
CROSS_SAID = {"deny": "Every read across a wall is stopped.", "ask": "You decide each time, for one session."}
SERVICES = "Connected services"
ADD_SERVICE = "Add a service"
NO_SERVICE = "No service yet."
BEHIND = "a file behind another zone's wall"
NOT_RECORDED = "not recorded"
WATCH_ONLY_NEXT = " Watch lets every result through, and notes that it could not decide."


CANNOT_NEXT = {"off": "", "warn": WATCH_ONLY_NEXT, "enforce": " While the read guard is On, every result from those tools is held back."}


def mode_choices(sg, current: str) -> str:
    """The three choices, each with what it does for you in one line under its name (#674)."""
    return ('<div class="rgmode" data-rg="mode" data-was="%s" role="radiogroup" aria-label="Read guard">%s</div>'
            % (sg.esc(current), "".join('<label class="rgchoice"><input type="radio" name="rg-mode" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
                                      % (k, " checked" if k == current else "", sg.esc(v), sg.esc(MODE_SAID[k])) for k, v in MODES)))


def cross_choices(sg, current: str) -> str:
    """Across a wall's two choices, each with what it does in one line under its name (#683)."""
    return ('<div class="rgmode rgcross" data-rg="cross" data-was="%s" role="radiogroup" aria-label="Across a wall">%s</div>'
            % (sg.esc(current), "".join('<label class="rgchoice"><input type="radio" name="rg-cross" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
                                      % (k, " checked" if k == current else "", sg.esc(v), sg.esc(CROSS_SAID[k])) for k, v in sg.CROSS)))


def service_line(sg, n: int, line: dict) -> str:
    """One connected service: its plain name, Check it and Leave it each with its line, and Not decided when neither is set."""
    name = line["name"] or sg.EVERY_SERVICE
    choices = "".join('<label class="rgchoice"><input type="radio" name="rg-svc-%d" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
                      % (n, k, " checked" if k == line["choice"] else "", sg.esc(v), sg.esc(said)) for k, v, said in sg.SERVICE_CHOICES)
    return ('<li class="rgsvc" data-service="%s" data-was="%s"><span class="rgsvcname">%s%s</span>'
            '<span class="rgchoices" role="radiogroup" aria-label="%s">%s</span></li>'
            % (sg.esc(line["name"]), sg.esc(line["choice"]), sg.esc(name),
               ' <small class="rgundecided">%s</small>' % sg.esc(sg.NOT_DECIDED) if not line["choice"] else "", sg.esc(name), choices))


def services_fold(sg, services: List[dict], help_button: Callable, help_text: Callable) -> str:
    """Connected services (#683): a closed fold named for what it holds, with how many are not decided in its name, one line for
    each service and *Add a service*. Its one "?" stands in the name; its text under the fold."""
    undecided = sum(1 for l in services if not l["choice"])
    title = SERVICES + (" (%d not decided)" % undecided if undecided else "")
    lines = "".join(service_line(sg, n, l) for n, l in enumerate(services)) or '<li class="rgnone hint">%s</li>' % sg.esc(NO_SERVICE)
    return ('<details class="rgadv rgsvcs" id="rg-services" data-for="warn enforce" data-undecided="%d"><summary><span id="rg-services-name">%s</span>%s</summary>'
            '<ul class="rgsvclist">%s</ul><span class="rgadd"><label for="rg-add-name">%s</label><input type="text" class="rgnew" id="rg-add-name" '
            'maxlength="60" autocomplete="off" placeholder="The name of the service">'
            '<button class="act sm" type="button" id="rg-add" data-rg-service-add="1">Add</button></span></details>%s'
            % (undecided, sg.esc(title), help_button(SERVICES, "rg-services"), lines, sg.esc(ADD_SERVICE),
               help_text("rg-services", sg.esc(TOOLS_TEXT))))


def as_time(value) -> dt.datetime:
    return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))


def kind_of(item: dict) -> str:
    """What a line is about: a file of the workspace, a file outside it, a mail or calendar result (also a line 0.78.0 wrote for an
    mcp__ tool), or a line 0.78.0 wrote for anything else, which says none of these."""
    if item.get("file"):
        return "file"
    if item.get("outside"):
        return "outside"
    if item.get("source") or str(item.get("tool", "")).startswith("mcp__"):
        return "mail"
    return "old"


def fold(items: List[dict]) -> List[dict]:
    """The lines of one zone's sessions, newest first, with the reads of one file in one session folded into one, and a count
    (#674). A line from 0.78.0 has no session: it folds with another of the same hash and tool."""
    groups: Dict[tuple, dict] = {}
    for i in sorted(items, key=lambda x: as_time(x["when"]), reverse=True):
        kind = kind_of(i)
        key = {"file": (kind, i.get("session"), i.get("file")), "outside": (kind, i.get("session"), i.get("id")),
               "mail": (kind, i.get("session"), i.get("tool"), i.get("held_zone")), "old": (kind, i.get("id"), i.get("tool"))}[kind]
        g = groups.setdefault(key, {"item": i, "kind": kind, "count": 0, "when": as_time(i["when"])})
        g["count"] += 1
    return list(groups.values())


def may_name(item: dict, shown: Optional[dict]) -> bool:
    """Whether the list may name this file: only a file of an open zone, in System/, or in Wikis/Knowledge. Any session can read the
    page, so the list fails closed: a file of a walled zone, of a zone the page does not know, or with no zone is never named, nor its
    project (#674 review W1, W2). `shown["walled"]` is each zone's flag."""
    path = item.get("file") or ""
    if item.get("part") == "System" or path.startswith("Wikis/Knowledge/"):
        return True
    zone = item.get("file_zone") or ""
    return bool(zone) and (shown or {}).get("walled", {}).get(zone, True) is False


def may_name_zone(zone: str, shown: Optional[dict]) -> bool:
    """Whether a held-back zone's name may be said: only an open zone's."""
    return bool(zone) and (shown or {}).get("walled", {}).get(zone, True) is False


def read_item(sg, g: dict, own: str, shown: Optional[dict]) -> str:
    """One line of the list: when, the session's project, what was read, the zone it belongs to, and how many times. Never what
    a file or a message says."""
    i, kind = g["item"], g["kind"]
    project = ("%s project" % i["project"]) if i.get("project") else "project %s" % NOT_RECORDED
    zone = ""
    if kind == "file":
        if may_name(i, shown):
            what = i["file"]
            zone = i.get("file_zone") or i.get("part") or ""
        else:
            what, project = BEHIND, ""
    elif kind == "outside":
        what = "a file outside the workspace"
    elif kind == "mail":                   # by the service's name, never the tool's (#683)
        what = "%s%s, a mail or calendar result" % (i.get("service") or "a connected service", " (%s)" % i["source"] if i.get("source") else "")
        held = i.get("held_zone")
        zone = ("held back from %s" % held if may_name_zone(held, shown) else "behind another zone's wall") if held else "zone %s" % NOT_RECORDED
    else:
        what = "%s: file %s" % (i.get("tool") or "a read", NOT_RECORDED)
    times = "%d times" % g["count"] if g["count"] > 1 else ""
    return ('<li class="rgread"><span class="rgwhen">%s</span> %s<span class="rgwhat">%s</span>%s%s</li>'
            % (sg.esc(g["when"].strftime("%d %b %H:%M")), '<span class="rgproj">%s</span> ' % sg.esc(project) if project else "", sg.esc(what),
               ' <span class="rgzone">(%s)</span>' % sg.esc(zone) if zone else "", ' <span class="rgcount">%s</span>' % times if times else ""))


def show_list(sg, would: Dict[str, List[dict]], shown: Optional[dict] = None) -> str:
    """The list behind *Show*: for each zone's sessions, what the log holds, folded, newest first. Each line names the time, the
    session's project, the file or the tool and its zone, and how many times."""
    out = ""
    for zone, items in would.items():
        body = "".join(read_item(sg, g, zone, shown) for g in fold(items)[:sg.LIST_MAX])
        out += '<div class="rglistzone"><b>%s sessions</b><ul>%s</ul></div>' % (sg.esc(zone), body)
    return out


def would_lines(sg, would: Dict[str, List[dict]]) -> List[str]:
    """The sentences under Watch: how many files, and how many sessions, would have been stopped, one line for each zone, since no
    count adds two zones. Files and sessions, never reads (#674)."""
    def plural(n: int, one: str, many: str) -> str:
        return "%d %s" % (n, one if n == 1 else many)
    if not would:
        return ["In the last %d days it would have stopped nothing." % sg.WINDOW_DAYS]
    out = []
    for zone, items in would.items():
        groups = fold(items)
        files = sum(1 for g in groups if g["kind"] != "mail")
        results = sum(1 for g in groups if g["kind"] == "mail")
        sessions = len({i.get("session") for i in items if i.get("session")})
        what = " and ".join(p for p in (plural(files, "file", "files") if files else "", plural(results, "mail or calendar result", "mail or calendar results") if results else "") if p)
        out.append("In the last %d days it would have stopped %s%s in %s." % (sg.WINDOW_DAYS, what, " across %s" % plural(sessions, "session", "sessions") if sessions else "", zone))
    return out


def guard_block(sg, state: dict, codex: bool, help_button: Callable, help_text: Callable, role: str = "solo", shown: Optional[dict] = None) -> str:
    """Settings › Walls › Read guard (#674, #682): a part of Walls, after the zones, in the app only. One sub-heading with one "?",
    one sentence on what it protects, the
    three choices each with what it does, and under Watch what the log holds, as a list that names each file and its zone. Across a wall
    is on the page under On only, and the connected services under Watch and On only, in a closed fold of their own (#683). Under Off
    neither is drawn: the page is built again once the mode is saved. The services give way to one line for Codex, which cannot have a
    result replaced. On a laptop copy the rows give way to one line: the read guard's settings are the workspace's, and this computer
    only receives it. `shown` says what the page may name, as `{"scope": None for the whole workspace or the zones, "walled": {zone:
    whether walled}}`."""
    head = '<h4 class="setsubh">Read guard%s</h4>' % help_button("Read guard", "readguard")
    if role == "roaming":
        return ('<div class="setpart apponly" id="readguard-settings" hidden data-roaming="1">%s<p class="hint rgroaming" id="rg-roaming">%s</p></div>'
                % (head, sg.esc(sg.ROAMING_LINE)))
    mode = state["mode"]
    problem = state.get("problem") or ""
    mode_row = mode_choices(sg, mode)
    seen = ""
    if mode == "warn":
        would = state["would"]
        seen = ('<div class="rgseen" id="rg-seen" data-for="warn"><p class="hint rgline">%s%s</p>%s</div>'
                % (" ".join(sg.esc(l) for l in would_lines(sg, would)),
                   ' <button class="act sm rgsmall" type="button" id="rg-show" aria-expanded="false" aria-controls="rg-list">Show</button>' if would else "",
                   '<div class="rglist" id="rg-list" hidden>%s</div>' % show_list(sg, would, shown) if would else ""))
    if state.get("unreadable"):
        seen += '<p class="hint rgcannot" id="rg-unreadable" role="status">%s</p>' % sg.esc(sg.UNREADABLE)
    cannot = ""
    if problem:
        cannot = '<p class="hint rgcannot" id="rg-cannot" role="status">%s%s</p>' % (sg.esc(sg.CANNOT.get(problem, sg.CANNOT["parties"])), sg.esc(CANNOT_NEXT.get(mode, "")))
    cross_row = ""
    if mode == "enforce":
        cross_row = ('<div class="rgrow rgcrossrow" data-for="enforce"><p class="rgsub"><b>Across a wall</b></p>%s</div>'
                     % cross_choices(sg, state["cross"]))
    lists = ""
    if codex:
        lists = ('<p class="hint rgcodex" id="rg-codex">%s</p><p class="hint rgtrust" id="rg-trust">%s</p>'
                 % (sg.esc(sg.CODEX_LINE), sg.esc(CODEX_TRUST)))
    elif mode != "off" and state.get("services") is not None:
        lists = services_fold(sg, state["services"], help_button, help_text)
    return ('<div class="setpart apponly" id="readguard-settings" hidden>%s<p class="setlede">%s</p>%s%s%s%s%s'
            '<p class="hint rgsaid" id="rg-said" role="status" hidden></p></div>'
            % (head, sg.esc(PROTECTS), help_text("readguard", sg.esc(HELP_TEXT)), mode_row, seen + cannot, cross_row, lists))




def machine_section(sg, role: str, name: str, server: str, help_button: Callable, help_text: Callable) -> str:
    """Settings › About › This computer (#682): one row, its label, the role in words (for a laptop copy with the home
    server's name) and *Change…* in the app only; in a browser, the line that says it is changed in Garrick.app. The
    sentence for the role is said once, in the window that Change opens, and as the role's tooltip (#681): a small line has
    ten words at most. The window holds the three choices, as before."""
    words = dict(sg.ROLE_WORDS)
    role = role if role in words else "solo"
    shown = words[role] + (" of %s" % server if role == "roaming" and server else "")
    choices = "".join(
        '<label class="rolechoice"><input type="radio" name="role-pick" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
        % (k, " checked" if k == role else "", sg.esc(v), sg.esc(sg.ROLE_TEXT[k])) for k, v in sg.ROLE_WORDS)
    row = ('<div class="launcher-row srow mrole" id="machine-role" data-role="%s" data-name="%s" data-server="%s">'
           '<div class="slab"><span class="launcher-choice"><span>This computer</span></span></div>'
           '<div class="sctl"><span class="mrolesaid" id="machine-role-said" title="%s">%s</span>'
           '<button class="act sm apponly" type="button" id="role-change" data-rolechange="1">Change…</button></div>%s</div>%s'
           % (sg.esc(role), sg.esc(name), sg.esc(server), sg.esc(sg.ROLE_TEXT[role]), sg.esc(shown), help_button("This computer", "machine"),
              help_text("machine", sg.esc(MACHINE_TEXT))))
    dialog = ('<div id="role-dialog" class="rolebox" role="dialog" aria-modal="true" aria-labelledby="role-title" hidden><div class="rolepanel" id="role-form">'
              '<h3 id="role-title" tabindex="-1">This computer</h3><fieldset class="rolepick"><legend>This computer is</legend>%s</fieldset>'
              '<div class="rolefields"><label id="role-name-row">This computer\'s name (optional)'
              '<input type="text" id="role-name" maxlength="40" autocomplete="off" placeholder="laptop"></label>'
              '<label id="role-server-row" hidden>The home server\'s name'
              '<input type="text" id="role-server" maxlength="40" autocomplete="off" placeholder="mini"></label></div>'
              '<p class="rolesays" id="role-says" aria-live="polite"></p><p class="hint rolefoot">%s</p>'
              '<p class="roleerr" id="role-err" role="alert" hidden></p>'
              '<div class="roleacts"><button class="act lg" type="button" id="role-yes">Change the role</button>'
              '<button class="act lg" type="button" id="role-no">Cancel</button></div></div>'
              '<script type="application/json" id="role-changes">%s</script></div>'
              % (choices, sg.esc(sg.ROLE_FOOT), json.dumps(sg.ROLE_CHANGES).replace("<", "\\u003c")))
    return ('<div class="setpart" id="machine-settings">%s<p class="hint nohost-only">The role is changed in Garrick.app.</p>%s</div>'
            % (row, dialog))


CSS = r"""
/* Settings › This machine and Settings › Read guard (#621, #674): rows are the page's grid; what is here is the guard's own */
.nohost-only{display:none}.nohost .nohost-only{display:block}
#machine-settings .mrole{align-items:center}.mrolesaid{font-size:var(--fs-meta);color:var(--ink2)}
.rolebox{position:fixed;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(0,0,0,.35)}.rolebox[hidden]{display:none}
.rolepanel{max-width:min(520px,100%);width:100%;max-height:100%;overflow:auto;box-sizing:border-box;padding:18px 20px;border:1px solid var(--line);border-radius:12px;color:var(--ink);background:var(--surface)}
.rolebox h3{margin:0 0 10px}.rolepick{border:0;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}.rolepick legend{font-size:var(--fs-meta);color:var(--muted);padding:0;margin-bottom:6px}
.rolechoice{display:flex;gap:8px;align-items:flex-start;padding:8px 10px;border:1px solid var(--line);border-radius:10px;cursor:pointer}
.rolechoice:has(input:checked){border-color:var(--accent);background:var(--wash)}
.rolechoice small{display:block;color:var(--muted);font-size:var(--fs-meta);font-weight:400}
.rolefields{display:flex;flex-direction:column;gap:8px;margin:12px 0 4px}.rolefields label{display:flex;flex-direction:column;gap:3px;font-size:var(--fs-meta);color:var(--muted)}
.rolefields input{font:inherit;font-size:var(--fs-body);padding:5px 8px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px}
.rolesays{margin:10px 0 4px;font-size:var(--fs-body);color:var(--ink)}.roleerr{margin:6px 0;color:var(--critical);font-size:var(--fs-meta)}
.roleacts{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
#readguard-settings[hidden]{display:none}
.rgmode{display:flex;flex-direction:column;gap:8px;margin:6px 0}.rgchoices{display:inline-flex;gap:12px;flex-wrap:wrap;align-items:center}
.rgchoice{display:inline-flex;gap:8px;align-items:flex-start;font-size:var(--fs-meta)}.rgmode .rgchoice{display:flex}.rgchoice small{display:block;color:var(--muted);font-size:var(--fs-meta);font-weight:400}
.rgchoice b{font-weight:560}.rgchoice input{margin-top:1px}
.rgrow[hidden],.rgwatch[hidden]{display:none}.rglist-row{align-items:flex-start}.rgbody{display:block}.rgitems{list-style:none;margin:0 0 6px;padding:0;display:flex;flex-direction:column;gap:4px}
.rgitem{display:flex;align-items:center;gap:8px;font-size:var(--fs-meta)}.rgitem .rgtool{flex:1;min-width:0;overflow-wrap:anywhere;font-family:var(--mono,monospace)}
.rgadd{display:flex;gap:6px;align-items:center}.rgadd input{flex:1;min-width:0;font:inherit;font-size:var(--fs-meta);padding:3px 7px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px}
.rgseen,.rgcannot,.rgcodex,.rgtrust,.rgfoot,.rgsaid,.rgwatch{margin:4px 0}.rgcannot{color:var(--critical)}
.rglist{margin:6px 0 0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;max-height:240px;overflow:auto;font-size:var(--fs-meta)}
.rglist ul{margin:2px 0 8px;padding-left:18px}.rglistzone b{font-weight:560}.rgread{margin:3px 0;overflow-wrap:anywhere}.rgwhen{color:var(--muted)}.rgcount{color:var(--muted)}.rgzone{color:var(--ink2)}
.rgadv{margin-top:8px}.rgadv>summary{display:block;list-style:none;cursor:pointer;font-size:var(--fs-meta);font-weight:560;color:var(--ink2);padding:3px 0}
.rgadv>summary::-webkit-details-marker{display:none}.rgadv>summary::before{content:'\25B8';display:inline-block;width:14px}.rgadv[open]>summary::before{content:'\25BE'}
.rgsub{margin:4px 0;font-size:var(--fs-meta)}
.rgsvcs>summary{display:flex;align-items:center;gap:6px}.rgsvcs>summary::before{flex:0 0 14px}
.rgsvclist{list-style:none;margin:4px 0 8px;padding:0;display:flex;flex-direction:column;gap:6px}
.rgsvc{display:flex;flex-wrap:wrap;align-items:flex-start;gap:4px 14px;font-size:var(--fs-meta)}.rgsvcname{flex:0 0 160px;min-width:0;overflow-wrap:anywhere;font-weight:560}
.rgsvcname small{display:block;font-weight:400;color:var(--critical)}.rgsvc .rgchoices{align-items:flex-start}
.rgadd label{font-size:var(--fs-meta);white-space:nowrap}
.rgsaid.bad{color:var(--critical)}.rgsaid details{margin-top:4px}.rgsaid pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0 0;font-size:var(--fs-meta)}
"""

JS = r"""
(function(){var rg=document.getElementById('readguard-settings');if(!rg)return;
/* Across a wall shows only under On, and its line under Watch (#674): what belongs to a mode shows with it */
function show(v){rg.querySelectorAll('[data-for]').forEach(function(e){e.hidden=e.dataset.for.split(' ').indexOf(v)<0})}
/* the parts show once the page's own handler has sent the change, and again if it is put back (the handler in settings_guard.py sends it on this same event) */
rg.addEventListener('change',function(e){var i=e.target;if(!i.matches('input[name="rg-mode"]'))return;
setTimeout(function(){var c=rg.querySelector('[data-rg="mode"] input:checked');if(c)show(c.value)},0)});
var prev=window.GarrickActed;window.GarrickActed=function(q,out){var r=prev?prev(q,out):undefined;
if(q&&q.verb==='read-guard'&&!(out&&out.ok)){var m=rg.querySelector('[data-rg="mode"]');if(m)show(m.dataset.was)}return r};
})();
"""
