#!/usr/bin/env python3
"""settings_readguard.py: Settings > Read guard and Settings > This machine, as the grid draws them (#673, #674).

settings_guard.py keeps what the read guard is and what its log holds: the hook folders it trusts, the log's lines, `read_state()`.
This file only draws, from what those give: one section for the read guard with one heading and one "?", the three choices each with
what it does, a list that names each file and its zone, *Across a wall* only under On, the tool patterns under a closed *Advanced*, and
the machine's row in the page's grid. It reads and writes nothing. Every function takes the settings_guard module as `sg`, for its words.
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
PROTECTS = "In a session for one project, the assistant does not open notes, meetings or mail that sit behind another zone's wall."
HELP_TEXT = ("Walls already stop your assistant from writing one zone's material into another. The read guard does the same for "
             "reading. In a session for one project, it stops the assistant from opening notes, meetings and mail that sit behind "
             "another wall. Watch and On add the read guard to your assistant's settings on this computer. Off takes it out. Start "
             "with Watch for a week and look at the list. When the list holds nothing you needed, choose On.")
WATCH_NEXT = ("Under Watch, Across a wall does nothing yet. Once you choose On, Refuse stops a read across a wall, and Ask me asks "
              "you each time.")
BEHIND = "a file behind another zone's wall"
NOT_RECORDED = "not recorded"
WATCH_ONLY_NEXT = " Watch lets every result through, and notes that it could not decide."


CANNOT_NEXT = {"off": "", "warn": WATCH_ONLY_NEXT, "enforce": " While the read guard is On, every result from those tools is held back."}


def mode_choices(sg, current: str) -> str:
    """The three choices, each with what it does for you in one line under its name (#674)."""
    return ('<div class="rgmode" data-rg="mode" data-was="%s" role="radiogroup" aria-label="Read guard">%s</div>'
            % (sg.esc(current), "".join('<label class="rgchoice"><input type="radio" name="rg-mode" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
                                      % (k, " checked" if k == current else "", sg.esc(v), sg.esc(MODE_SAID[k])) for k, v in MODES)))


def item_list(sg, key: str, items: List[str], label: str) -> str:
    rows = "".join('<li class="rgitem" data-item="%s"><span class="rgtool">%s</span>'
                   '<button class="act sm rgrem" type="button" data-rg-remove="%s" data-list="%s" aria-label="Remove %s">Remove</button></li>'
                   % (sg.esc(i), sg.esc(i), sg.esc(i), key, sg.esc(i)) for i in items) or '<li class="rgnone hint">None.</li>'
    return ('<ul class="rgitems" data-list="%s">%s</ul><span class="rgadd"><input type="text" class="rgnew" data-list="%s" '
            'maxlength="100" autocomplete="off" aria-label="%s" placeholder="mcp__*Mail*">'
            '<button class="act sm" type="button" data-rg-add="%s">Add</button></span>' % (key, rows, key, sg.esc(label), key))


def as_time(value) -> dt.datetime:
    return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))


def kind_of(item: dict) -> str:
    """What a line is about: a file of the workspace, a file outside it, a mail or calendar result, or a line 0.78.0 wrote, which
    says none of these."""
    if item.get("file"):
        return "file"
    if item.get("outside"):
        return "outside"
    if item.get("source"):
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


def may_name(zone: str, own: str, shown: Optional[dict]) -> bool:
    """Whether the list may name a file or a result of `zone`, in a session of `own`: always on the page as it is built, for the
    whole workspace; where it is shown for fewer zones (`scope`), only the zone's own, an open zone's, or one in scope. A zone
    the page does not know is walled."""
    scope = (shown or {}).get("scope")
    if scope is None or not zone or zone == own or zone in scope:
        return True
    return (shown.get("walled") or {}).get(zone, True) is False


def read_item(sg, g: dict, own: str, shown: Optional[dict]) -> str:
    """One line of the list: when, the session's project, what was read, the zone it belongs to, and how many times. Never what
    a file or a message says."""
    i, kind = g["item"], g["kind"]
    project = ("%s project" % i["project"]) if i.get("project") else "project %s" % NOT_RECORDED
    zone = ""
    if kind == "file":
        owner = i.get("file_zone") or ""
        if may_name(owner, own, shown):
            what = i["file"]
            zone = owner or i.get("part") or ""
        else:
            what = BEHIND
    elif kind == "outside":
        what = "a file outside the workspace"
    elif kind == "mail":
        what = "%s (%s), a mail or calendar result" % (i.get("tool", ""), i["source"])
        held = i.get("held_zone")
        zone = ("held back from %s" % held if may_name(held, own, shown) else "behind another zone's wall") if held else "zone %s" % NOT_RECORDED
    else:
        what = "%s: file %s" % (i.get("tool") or "a read", NOT_RECORDED)
    times = "%d times" % g["count"] if g["count"] > 1 else ""
    return ('<li class="rgread"><span class="rgwhen">%s</span> <span class="rgproj">%s</span> <span class="rgwhat">%s</span>%s%s</li>'
            % (sg.esc(g["when"].strftime("%d %b %H:%M")), sg.esc(project), sg.esc(what),
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
    """Settings › Read guard (#674): its own section, in the app only. One heading with one "?", one sentence on what it protects, the
    three choices each with what it does, and under Watch what the log holds, as a list that names each file and its zone. Across a wall
    shows only under On. The tool patterns are under a closed Advanced. The two tool lists give way to one line for Codex, which cannot
    have a result replaced. On a laptop copy the rows give way to one line: the read guard's settings are the workspace's, and this
    computer only receives it. `shown` says what the page may name, as `{"scope": None for the whole workspace or the zones, "walled":
    {zone: whether walled}}`."""
    head = '<h3>Read guard%s</h3>' % help_button("Read guard", "readguard")
    if role == "roaming":
        return ('<section class="setsec apponly" id="readguard-settings" hidden data-roaming="1">%s<p class="hint rgroaming" id="rg-roaming">%s</p></section>'
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
    watch = '<p class="hint rgwatch" id="rg-cross-watch" data-for="warn"%s>%s</p>' % ("" if mode == "warn" else " hidden", sg.esc(WATCH_NEXT))
    cross_row = ('<div class="launcher-row srow rgrow" data-rg="cross" data-was="%s" data-for="enforce"%s><div class="slab"><span class="launcher-choice"><span>Across a wall</span></span></div>'
                 '<div class="sctl">%s</div>%s</div>%s'
                 % (sg.esc(state["cross"]), "" if mode == "enforce" else " hidden", sg.radios("rg-cross", "cross", sg.CROSS, state["cross"], "Across a wall"),
                    help_button("Across a wall: Refuse, Ask me", "rg-cross"), help_text("rg-cross", sg.esc(sg.GUARD_TEXT["rg-cross"]))))
    if codex:
        lists = ('<p class="hint rgcodex" id="rg-codex">%s</p><p class="hint rgtrust" id="rg-trust">%s</p>'
                 % (sg.esc(sg.CODEX_LINE), sg.esc(sg.CODEX_TRUST)))
    else:
        def list_row(key: str, name: str, label: str, text_key: str) -> str:
            return ('<div class="launcher-row srow rgrow rglist-row" data-rg="%s"><div class="slab"><span class="launcher-choice"><span>%s</span></span></div>'
                    '<div class="sctl rgbody">%s</div>%s</div>%s'
                    % (key, sg.esc(name), item_list(sg, key, state[key], label), help_button(name, text_key), help_text(text_key, sg.esc(sg.GUARD_TEXT[text_key]))))
        lists = ('<details class="rgadv"><summary>Advanced</summary><p class="rgsub"><b>Which connected tools are checked</b></p>%s%s</details>'
                 % (list_row("tools", "Mail and calendar tools", "A mail or calendar tool to check", "rg-tools"),
                    list_row("skip", "Tools with nothing to check", "A tool with nothing to check", "rg-skip")))
    return ('<section class="setsec apponly" id="readguard-settings" hidden data-tools="%s" data-skip="%s">%s<p class="setlede">%s</p>%s%s%s%s%s%s%s'
            '<p class="hint rgsaid" id="rg-said" role="status" hidden></p></section>'
            % (sg.esc(json.dumps(state["tools"])), sg.esc(json.dumps(state["skip"])), head, sg.esc(PROTECTS),
               help_text("readguard", sg.esc(HELP_TEXT)), mode_row, seen + cannot, watch, cross_row, lists, ""))




def machine_section(sg, role: str, name: str, server: str, help_button: Callable, help_text: Callable) -> str:
    """Settings › This machine. The role in words and, for a laptop copy, the home server's name; *Change…* in the app only;
    in a browser, the line that says it is changed in Garrick.app. The dialog holds the three choices."""
    words = dict(sg.ROLE_WORDS)
    role = role if role in words else "solo"
    shown = words[role] + (" of %s" % server if role == "roaming" and server else "")
    choices = "".join(
        '<label class="rolechoice"><input type="radio" name="role-pick" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
        % (k, " checked" if k == role else "", sg.esc(v), sg.esc(sg.ROLE_TEXT[k])) for k, v in sg.ROLE_WORDS)
    row = ('<div class="launcher-row srow mrole" id="machine-role" data-role="%s" data-name="%s" data-server="%s">'
           '<div class="slab"><span class="launcher-choice"><span id="machine-role-said">%s<small>%s</small></span></span></div>'
           '<div class="sctl"><button class="act sm apponly" type="button" id="role-change" data-rolechange="1">Change…</button></div>%s</div>%s'
           % (sg.esc(role), sg.esc(name), sg.esc(server), sg.esc(shown), sg.esc(sg.ROLE_TEXT[role]), help_button("This computer's role", "machine-role"),
              help_text("machine-role", sg.esc(sg.ROLE_TEXT[role]))))
    dialog = ('<div id="role-dialog" class="rolebox" role="dialog" aria-modal="true" aria-labelledby="role-title" hidden><div class="rolepanel" id="role-form">'
              '<h3 id="role-title" tabindex="-1">This machine</h3><fieldset class="rolepick"><legend>This computer is</legend>%s</fieldset>'
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
    return ('<section class="setsec" id="machine-settings"><h3>This machine%s</h3><p class="setlede">%s</p>%s%s'
            '<p class="hint nohost-only">The role is changed in Garrick.app.</p>%s</section>'
            % (help_button("This machine", "machine"), sg.esc("Whether this computer works alone, holds the workspace, or keeps a copy of it."),
               help_text("machine", sg.esc(sg.MACHINE_TEXT)), row, dialog))


CSS = r"""
/* Settings › This machine and Settings › Read guard (#621, #674): rows are the page's grid; what is here is the guard's own */
.nohost-only{display:none}.nohost .nohost-only{display:block}
#machine-settings .mrole{align-items:center}
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
.rgsaid.bad{color:var(--critical)}.rgsaid details{margin-top:4px}.rgsaid pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0 0;font-size:var(--fs-meta)}
"""

JS = r"""
(function(){var rg=document.getElementById('readguard-settings');if(!rg)return;
/* Across a wall shows only under On, and its line under Watch (#674): what belongs to a mode shows with it */
function show(v){rg.querySelectorAll('[data-for]').forEach(function(e){e.hidden=e.dataset.for.split(' ').indexOf(v)<0})}
rg.addEventListener('change',function(e){var i=e.target;if(i.matches('input[name="rg-mode"]'))show(i.value)});
var prev=window.GarrickActed;window.GarrickActed=function(q,out){var r=prev?prev(q,out):undefined;
if(q&&q.verb==='read-guard'&&!(out&&out.ok)){var m=rg.querySelector('[data-rg="mode"]');if(m)show(m.dataset.was)}return r};
})();
"""
