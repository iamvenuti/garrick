#!/usr/bin/env python3
"""settings_guard.py: Settings › This machine, and the Read guard block in Settings › Walls (#621).

Two features that 0.73.0 shipped could only be set by hand: the role of a computer (#612) and the read guard with its
connector filter (#613, #614). Both are set here, in the app, with no terminal and no file edit:

- *This machine* shows the role in words, **One computer**, **Home server** or **Laptop copy**, and the server's name for a
  laptop copy. *Change…* opens a dialog with the three choices, each explained, says what changes on this computer and asks
  for a yes before anything is sent. In a browser the section shows the role and says it is changed in Garrick.app.
- The *Read guard* block has four rows: Off, Watch only or On; Refuse or Ask me across a wall; the mail and calendar tools
  the filter checks; and the tools with nothing to check. Under Watch only it says what the log holds: what the guard would
  have stopped in the last 7 days, one line for each zone, since no count adds two zones.

The words are the ones the docs use. The explanations are the issue's, word for word. This file builds markup and reads;
it writes nothing: the page's two verbs, `machine-role` and `read-guard`, do (page_action.py). Standard library only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
WINDOW_DAYS = 7
LIST_MAX = 50           # the most a list in Show names, newest first

# The three roles in the words a person reads, and what each is, word for word as the help says it.
ROLE_WORDS = (("solo", "One computer"), ("server", "Home server"), ("roaming", "Laptop copy"))
ROLE_TEXT = {
    "solo": "Everything happens here: your sessions, the nightly jobs and your Todo lists.",
    "server": "This computer is always on and holds the real workspace. The nightly jobs run here, and it applies the ticks "
              "your laptop sends.",
    "roaming": "This computer keeps a copy that only receives. You can read everything, even with no network. A tick on a "
               "Todo list waits until the home server applies it. Nightly jobs do not run here.",
}
MACHINE_TEXT = ("Most people use Garrick on one computer and can leave this as it is. Change it only if your workspace lives "
                "on a computer that stays on at home and a laptop keeps a copy of it. This setting stays on this computer, "
                "so the other computer keeps its own.")
# What the dialog says will change on this computer, for the choice made, before the yes.
ROLE_CHANGES = {
    "solo": "This computer works on its own again. Its sessions, jobs and Todo lists all run here.",
    "server": "This computer becomes the home server. Its nightly jobs keep running, and it applies the ticks a laptop sends. "
              "Set up the sync so the laptop receives the workspace from here.",
    "roaming": "This computer stops writing in the workspace. You can still read everything, ticks wait for the home server, "
               "and nightly jobs stop running here.",
}
ROLE_FOOT = "This changes this computer only. Nothing in your workspace changes, and the other computer keeps its own role."

GUARD_TEXT = {
    "readguard": "Walls already stop your assistant from writing one zone's material into another. The read guard does the "
                 "same for reading. In a session for one project, it stops the assistant from opening notes, meetings and "
                 "mail that sit behind another wall.",
    "rg-mode": "Watch only lets every read through and keeps a list of what it would have stopped. Start with it for a week "
               "and look at the list. When the list holds nothing you needed, choose On, and those reads are stopped.",
    "rg-cross": "Refuse stops every read across a wall, with no question. Ask me asks you each time, so you can allow one "
                "read for one session.",
    "rg-tools": "A mail or calendar search can return messages from every part of your life in one list. Before your "
                "assistant sees the list, Garrick removes what belongs behind another wall. These are the tools it checks. "
                "Add one when you connect a new mail or calendar service.",
    "rg-skip": "Tools that return nothing tied to a person or a company, such as a weather service. Garrick does not check "
               "them and does not warn you about them.",
}
CODEX_LINE = "Codex cannot have its mail and calendar results checked. Only the instructions keep them apart."
UNREADABLE = ("Garrick cannot read your settings file. The mail and calendar check treats the read guard as On until it reads "
              "again.")
CODEX_TRUST = "Codex runs the read guard only after you trust it in its hooks screen, and again after each change you make here."
MODES = (("off", "Off"), ("warn", "Watch only"), ("enforce", "On"))
CROSS = (("deny", "Refuse"), ("ask", "Ask me"))
CANNOT = {
    "parties": "Garrick cannot read the list of parties it matches addresses against, so the mail and calendar check cannot run.",
    "intake": "A part of Garrick that matches addresses is missing, so the mail and calendar check cannot run. Update Garrick.",
}
CANNOT_NEXT = {
    "off": "",
    "warn": " Watch only lets every result through, and notes that it could not decide.",
    "enforce": " While the read guard is On, every result from those tools is held back.",
}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


# ---------------------------------------------------------------------------------------------------- what the guard holds


HOOK_NAME = re.compile(r".*(?:zone_guard|read_guard|waiting_hook)\.py", re.S)

# The two files that make a hooks folder Garrick's, with the SHA-256 of each as this release ships it. A folder an assistant's
# settings name is only trusted when both files read the same as the ones beside this page, or, where this page has none
# beside it (an installed page), the same as these digests. A planted copy, and a file of an older Garrick, pass neither.
# `tests/test_settings_actions.py` fails when a release changes a hook file and leaves its digest here behind.
RELEASE_HOOKS = {
    "zone_guard.py": "c78a9f7a3a602dc7aaefc46d448397323897629ce2b6a9374c0cffc1563ef799",
    "read_guard.py": "da3bb1e310c57bbdc98578b35f4cb4522dd6375c15981ef4da6e216ee140734c",
}


def _bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def trusted_hook_folder(folder: Path) -> bool:
    """Whether `folder` holds Garrick's own `zone_guard.py` and `read_guard.py`, as this release ships them. The folder
    beside the page passes; any other passes only on the same bytes. Reads the files; never imports them."""
    beside = HERE.parent / "hooks"
    try:
        if folder.resolve() == beside.resolve() and (folder / "read_guard.py").is_file():
            return True
    except OSError:
        return False
    for name, digest in RELEASE_HOOKS.items():
        have = _bytes(folder / name)
        if have is None:
            return False
        ours = _bytes(beside / name)
        if ours is not None:
            if have != ours:
                return False
        elif hashlib.sha256(have).hexdigest() != digest:
            return False
    return True


def hook_scripts(text: str) -> List[str]:
    """The Garrick hook files an assistant's settings text names: the words of each hook `command`, split as a shell splits
    them, that end in zone_guard.py, read_guard.py or waiting_hook.py. A path with a space in it stays whole when quoted.
    A text that is not JSON names none."""
    out: List[str] = []

    def walk(node):
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str):
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = command.split()
                out.extend(w for w in words if HOOK_NAME.fullmatch(w))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    try:
        walk(json.loads(text))
    except ValueError:
        pass
    return out


def hook_folders(home: Optional[str] = None) -> List[Path]:
    """Where read_guard.py can be: `extras/hooks/` beside the status page in a clone, then the folder of any Garrick hook
    the assistants' settings already point at (the zone guard runs from the Garrick you keep outside the workspace). A
    folder a settings file names is kept only when `trusted_hook_folder` says it holds Garrick's own two files. The
    workspace has no copy of its own: the hooks stay where the Garrick download is."""
    home = home or str(Path.home())
    folders = [HERE.parent / "hooks"]
    for rel in (".claude/settings.json", ".codex/hooks.json"):
        try:
            text = (Path(home) / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        for found in hook_scripts(text):
            there = Path(os.path.expanduser(found))
            if there.is_absolute():
                folders.append(there.parent)
    out = []
    for f in folders:
        if f not in out and (f / "read_guard.py").is_file() and trusted_hook_folder(f):
            out.append(f)
    return out


def load_hook(folder: Path, name: str):
    """read_guard.py from a folder `hook_folders()` returned, or an exception. The standard modules it imports are loaded
    first, so a file beside it cannot stand in for one; the folder goes last on the path, not first."""
    import hashlib, json, os, re, shlex, sys, tempfile, time, types  # noqa: F401,E401
    src = folder / "read_guard.py"
    spec = importlib.util.spec_from_file_location(name, str(src))
    mod = importlib.util.module_from_spec(spec)
    added = str(folder) not in sys.path
    if added:
        sys.path.append(str(folder))
    try:
        spec.loader.exec_module(mod)
    finally:
        if added and str(folder) in sys.path:
            sys.path.remove(str(folder))
    return mod, src


def guard_module():
    """read_guard.py, from the first of `hook_folders()` that loads, or None."""
    for folder in hook_folders():
        try:
            return load_hook(folder, "garrick_read_guard_settings")[0]
        except Exception:
            continue
    return None


def log_lines(folder: Path, now: dt.datetime, days: int = WINDOW_DAYS) -> List[dict]:
    """What the read guard's log holds from the last `days`: its lines as the hook wrote them, a time, a tool, a decision, the
    scope's zone and a hash. Never a path, a party, a title or a count: the log has none to show."""
    cutoff = now - dt.timedelta(days=days)
    out = []
    for name in ("read-guard.log.1", "read-guard.log"):
        try:
            text = (Path(folder) / name).read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                item = json.loads(line)
                when = dt.datetime.strptime(str(item["t"])[:19], "%Y-%m-%dT%H:%M:%S")
            except (ValueError, KeyError, TypeError):
                continue
            if when >= cutoff and isinstance(item, dict):
                out.append(dict(item, when=when))
    return sorted(out, key=lambda i: i["when"], reverse=True)


def would_have_stopped(lines: List[dict]) -> Dict[str, List[dict]]:
    """The lines that are a read the guard would have stopped, by the zone of the session that made it: one list for each
    zone, so no figure adds two zones. A session at the workspace root has no zone and no line here."""
    out: Dict[str, List[dict]] = {}
    for item in lines:
        if item.get("decision") in ("deny", "confirm") and item.get("zone") and item.get("zone") not in ("root", "other", "wiki"):
            out.setdefault(str(item["zone"]), []).append(item)
    return dict(sorted(out.items(), key=lambda kv: kv[0].casefold()))


def read_state(ws: Path, lib, home: Optional[Path] = None, now: Optional[dt.datetime] = None) -> dict:
    """What Settings shows of the read guard: whether its hook is registered, its mode and cross-wall choice, both lists,
    whether the connector filter can run, and what the log holds. Reads only; never raises."""
    home = Path(home) if home is not None else Path.home()
    state = {"registered": False, "mode": "off", "cross": "deny", "tools": [], "skip": [], "problem": "", "would": {}, "unreadable": False}
    try:
        state["cross"] = lib.read_guard_cross(ws)
        state["tools"] = list(lib.connector_patterns(ws))
        state["skip"] = list(lib.connector_skips(ws))
        state["problem"] = lib.connector_filter_problem(ws)
    except Exception:
        pass
    guard = guard_module()
    try:
        lines, _ = guard.check_lines(str(home)) if guard is not None else ([], False)
        state["registered"] = bool(lines) and all("is registered" in l for l in lines)
    except Exception:
        pass
    try:
        on = lib.read_guard_mode(ws)
        state["mode"] = "off" if not state["registered"] else ("enforce" if on == "enforce" else "warn")
        if state["registered"] and not lib.settings_readable(ws):
            state["mode"], state["unreadable"] = "enforce", True      # the connector filter reads such a file as On
    except Exception:
        pass
    try:
        state["would"] = would_have_stopped(log_lines(lib.read_guard_dir(), now or dt.datetime.now()))
    except Exception:
        pass
    return state


# ---------------------------------------------------------------------------------------------------- markup


def machine_section(role: str, name: str, server: str, help_button: Callable, help_text: Callable) -> str:
    """Settings › This machine. The role in words and, for a laptop copy, the home server's name; *Change…* in the app only;
    in a browser, the line that says it is changed in Garrick.app. The dialog holds the three choices."""
    words = dict(ROLE_WORDS)
    role = role if role in words else "solo"
    shown = words[role] + (" of %s" % server if role == "roaming" and server else "")
    choices = "".join(
        '<label class="rolechoice"><input type="radio" name="role-pick" value="%s"%s> <span><b>%s</b><small>%s</small></span></label>'
        % (k, " checked" if k == role else "", esc(v), esc(ROLE_TEXT[k])) for k, v in ROLE_WORDS)
    row = ('<div class="launcher-row mrole" id="machine-role" data-role="%s" data-name="%s" data-server="%s">'
           '<span class="launcher-choice"><span id="machine-role-said">%s<small>%s</small></span></span>'
           '<button class="act apponly" type="button" id="role-change" data-rolechange="1">Change…</button>%s</div>%s'
           % (esc(role), esc(name), esc(server), esc(shown), esc(ROLE_TEXT[role]), help_button("This computer's role", "machine-role"),
              help_text("machine-role", esc(ROLE_TEXT[role]))))
    dialog = ('<div id="role-dialog" class="rolebox" role="dialog" aria-modal="true" aria-labelledby="role-title" hidden><div class="rolepanel" id="role-form">'
              '<h3 id="role-title" tabindex="-1">This machine</h3><fieldset class="rolepick"><legend>This computer is</legend>%s</fieldset>'
              '<div class="rolefields"><label id="role-name-row">This computer\'s name (optional)'
              '<input type="text" id="role-name" maxlength="40" autocomplete="off" placeholder="laptop"></label>'
              '<label id="role-server-row" hidden>The home server\'s name'
              '<input type="text" id="role-server" maxlength="40" autocomplete="off" placeholder="mini"></label></div>'
              '<p class="rolesays" id="role-says" aria-live="polite"></p><p class="hint rolefoot">%s</p>'
              '<p class="roleerr" id="role-err" role="alert" hidden></p>'
              '<div class="roleacts"><button class="act" type="button" id="role-yes">Change the role</button>'
              '<button class="act" type="button" id="role-no">Cancel</button></div></div>'
              '<script type="application/json" id="role-changes">%s</script></div>'
              % (choices, esc(ROLE_FOOT), json.dumps(ROLE_CHANGES).replace("<", "\\u003c")))
    return ('<section class="setsec" id="machine-settings"><h3>This machine%s</h3><p class="setlede">%s</p>%s%s'
            '<p class="hint nohost-only">The role is changed in Garrick.app.</p>%s</section>'
            % (help_button("This machine", "machine"), esc("Whether this computer works alone, holds the workspace, or keeps a copy of it."),
               help_text("machine", esc(MACHINE_TEXT)), row, dialog))


def radios(name: str, group: str, choices, current: str, label: str, help_btn: str = "") -> str:
    return ('<span class="rgchoices" role="radiogroup" aria-label="%s">%s</span>'
            % (esc(label), "".join('<label class="rgchoice"><input type="radio" name="%s" value="%s"%s> %s</label>'
                                   % (name, esc(k), " checked" if k == current else "", esc(v)) for k, v in choices)))


def item_list(key: str, items: List[str], label: str) -> str:
    rows = "".join('<li class="rgitem" data-item="%s"><span class="rgtool">%s</span>'
                   '<button class="act rgrem" type="button" data-rg-remove="%s" data-list="%s" aria-label="Remove %s">Remove</button></li>'
                   % (esc(i), esc(i), esc(i), key, esc(i)) for i in items) or '<li class="rgnone hint">None.</li>'
    return ('<ul class="rgitems" data-list="%s">%s</ul><span class="rgadd"><input type="text" class="rgnew" data-list="%s" '
            'maxlength="100" autocomplete="off" aria-label="%s" placeholder="mcp__*Mail*">'
            '<button class="act" type="button" data-rg-add="%s">Add</button></span>' % (key, rows, key, esc(label), key))


def show_list(would: Dict[str, List[dict]]) -> str:
    """The list behind *Show*: what the log holds for each zone, a time, the tool and the decision, newest first."""
    out = ""
    for zone, items in would.items():
        body = "".join("<li>%s, %s, %s</li>" % (esc(i["when"].strftime("%d %b %H:%M")), esc(i.get("tool", "")),
                                                  esc("would be stopped" if i.get("decision") == "deny" else "would ask you"))
                       for i in items[:LIST_MAX])
        out += '<div class="rglistzone"><b>%s sessions</b><ul>%s</ul></div>' % (esc(zone), body)
    return out


def would_lines(would: Dict[str, List[dict]]) -> str:
    """The sentence under Watch only: one line, or one for each zone when sessions of more than one zone are in the log."""
    def said(n: int) -> str:
        return "no reads" if n == 0 else "1 read" if n == 1 else "%d reads" % n
    if len(would) <= 1:
        n = sum(len(v) for v in would.values())
        zone = " in %s sessions" % next(iter(would)) if would else ""
        return ['In the last %d days it would have stopped %s%s.' % (WINDOW_DAYS, said(n), zone)]
    return ["In %s sessions, in the last %d days it would have stopped %s." % (z, WINDOW_DAYS, said(len(v))) for z, v in would.items()]


def title(text: str, button: str) -> str:
    return '<span class="rgtitle">%s%s</span>' % (esc(text), button)


ROAMING_LINE = "The read guard is set on the home server."


def guard_block(state: dict, codex: bool, help_button: Callable, help_text: Callable, role: str = "solo") -> str:
    """The Read guard block of Settings › Walls: four rows, in the app only. Under Watch only, what the log holds. The two
    tool lists give way to one line for Codex, which cannot have a result replaced. On a laptop copy the rows give way to
    one line: the read guard's settings are the workspace's, and this computer only receives it."""
    if role == "roaming":
        return ('<div class="rgblock apponly" id="readguard-settings" hidden data-roaming="1"><h4 class="nsub">Read guard</h4>'
                '<p class="hint rgroaming" id="rg-roaming">%s</p></div>' % esc(ROAMING_LINE))
    mode = state["mode"]
    problem = state.get("problem") or ""
    mode_row = ('<div class="rgrow" data-rg="mode" data-was="%s">%s%s</div>%s'
                '<p class="hint rgfoot">Watch only and On add the read guard to your assistant\'s settings on this computer. Off takes it out.</p>'
                % (esc(mode), title("Read guard", help_button("Read guard: Off, Watch only, On", "rg-mode")),
                   radios("rg-mode", "mode", MODES, mode, "Read guard"), help_text("rg-mode", esc(GUARD_TEXT["rg-mode"]))))
    seen = ""
    if mode == "warn":
        lines = would_lines(state["would"])
        seen = ('<div class="rgseen" id="rg-seen"><p class="hint rgline">%s%s</p>%s</div>'
                % (" ".join(esc(l) for l in lines),
                   ' <button class="act rgsmall" type="button" id="rg-show" aria-expanded="false" aria-controls="rg-list">Show</button>' if state["would"] else "",
                   '<div class="rglist" id="rg-list" hidden>%s</div>' % show_list(state["would"]) if state["would"] else ""))
    if state.get("unreadable"):
        seen += '<p class="hint rgcannot" id="rg-unreadable" role="status">%s</p>' % esc(UNREADABLE)
    cannot = ""
    if problem:
        cannot = '<p class="hint rgcannot" id="rg-cannot" role="status">%s%s</p>' % (esc(CANNOT.get(problem, CANNOT["parties"])), esc(CANNOT_NEXT.get(mode, "")))
    cross_row = ('<div class="rgrow" data-rg="cross" data-was="%s">%s%s</div>%s'
                 % (esc(state["cross"]), title("Across a wall", help_button("Across a wall: Refuse, Ask me", "rg-cross")),
                    radios("rg-cross", "cross", CROSS, state["cross"], "Across a wall"), help_text("rg-cross", esc(GUARD_TEXT["rg-cross"]))))
    if codex:
        lists = ('<p class="hint rgcodex" id="rg-codex">%s</p><p class="hint rgtrust" id="rg-trust">%s</p>'
                 % (esc(CODEX_LINE), esc(CODEX_TRUST)))
    else:
        lists = ('<div class="rgrow rglist-row" data-rg="tools">%s<div class="rgbody">%s</div></div>%s'
                 '<div class="rgrow rglist-row" data-rg="skip">%s<div class="rgbody">%s</div></div>%s'
                 % (title("Mail and calendar tools", help_button("Mail and calendar tools", "rg-tools")),
                    item_list("tools", state["tools"], "A mail or calendar tool to check"), help_text("rg-tools", esc(GUARD_TEXT["rg-tools"])),
                    title("Tools with nothing to check", help_button("Tools with nothing to check", "rg-skip")),
                    item_list("skip", state["skip"], "A tool with nothing to check"), help_text("rg-skip", esc(GUARD_TEXT["rg-skip"]))))
    return ('<div class="rgblock apponly" id="readguard-settings" hidden data-tools="%s" data-skip="%s"><h4 class="nsub">Read guard%s</h4>%s%s%s%s%s'
            '<p class="hint rgsaid" id="rg-said" role="status" hidden></p></div>'
            % (esc(json.dumps(state["tools"])), esc(json.dumps(state["skip"])), help_button("Read guard", "readguard"),
               help_text("readguard", esc(GUARD_TEXT["readguard"])), mode_row, seen + cannot, cross_row, lists))


# ---------------------------------------------------------------------------------------------------- style and script

# New rules only, in a block of their own: nothing here changes a token or a rule of the page's.
CSS = r"""
/* Settings › This machine and Settings › Walls › Read guard (#621) */
.nohost-only{display:none}.nohost .nohost-only{display:block}
.launcher-row .qhelp{margin-left:8px;align-self:center}.rgtitle .qhelp{margin-left:0}
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
.rgblock{margin:12px 0 0;padding-top:10px;border-top:1px solid var(--line)}.rgblock .nsub{margin:0 0 6px}
.rgblock[hidden]{display:none}.rgchoices{display:inline-flex;gap:12px;flex-wrap:wrap;align-items:center}.rgchoice{display:inline-flex;gap:5px;align-items:center;font-size:var(--fs-body)}
.rgrow{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;padding:4px 0}.rgtitle{flex:0 0 190px;display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-body)}
.rglist-row{align-items:flex-start}.rgbody{flex:1 1 260px;min-width:0}.rgitems{list-style:none;margin:0 0 6px;padding:0;display:flex;flex-direction:column;gap:4px}
.rgitem{display:flex;align-items:center;gap:8px;font-size:var(--fs-meta)}.rgitem .rgtool{flex:1;min-width:0;overflow-wrap:anywhere;font-family:var(--mono,monospace)}
.rgadd{display:flex;gap:6px;align-items:center}#readguard-settings .rgsmall,#readguard-settings .rgrem,#readguard-settings .rgadd .act{padding:2px 9px;min-height:0;line-height:1.5;font-size:var(--fs-meta)}.rgadd input{flex:1;min-width:0;font:inherit;font-size:var(--fs-meta);padding:3px 7px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:7px}
.rgseen,.rgcannot,.rgcodex,.rgtrust,.rgfoot,.rgsaid{margin:4px 0}.rgcannot{color:var(--critical)}.rglist{margin:6px 0 0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;max-height:200px;overflow:auto;font-size:var(--fs-meta)}
.rglist ul{margin:2px 0 8px;padding-left:18px}.rglistzone b{font-weight:560}
.rgsaid.bad{color:var(--critical)}.rgsaid details{margin-top:4px}.rgsaid pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0 0;font-size:var(--fs-meta)}
"""

JS = r"""
(function(){var host=window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.garrick,sd=document.getElementById('settings');
var ms=document.getElementById('machine-settings'),rg=document.getElementById('readguard-settings');if(!sd||!host||!(ms||rg))return;
if(rg)rg.hidden=false;
var pending=null,said=document.getElementById('rg-said');
function fix(t){return String(t==null?'':t)}
function send(q){if(pending)return false;pending=q;host.postMessage({act:q});return true}
/* what each reply does: a refusal puts the controls back as they were, says the one sentence and keeps the tool's words under Details */
function tell(out){if(!said)return;said.hidden=false;said.className='hint rgsaid'+(out.ok?'':' bad');said.textContent='';
var p=out.plain&&out.plain.say;said.appendChild(document.createTextNode(out.ok?fix(out.say):fix(p||'That did not work.')));
if(!out.ok&&out.say&&out.say!==p){var d=document.createElement('details'),s=document.createElement('summary'),pre=document.createElement('pre');
s.textContent='Details';pre.textContent=fix(out.say);d.appendChild(s);d.appendChild(pre);said.appendChild(d)}}
/* ---- the role ---- */
var dlg=document.getElementById('role-dialog');
if(ms&&dlg){var row=document.getElementById('machine-role'),pick=function(){var c=dlg.querySelector('input[name="role-pick"]:checked');return c?c.value:'solo'},
changes={};try{changes=JSON.parse(document.getElementById('role-changes').textContent)}catch(e){}
var srv=document.getElementById('role-server'),nm=document.getElementById('role-name'),err=document.getElementById('role-err');
function show(){var r=pick();document.getElementById('role-server-row').hidden=r!=='roaming';document.getElementById('role-name-row').hidden=r==='solo';
document.getElementById('role-says').textContent=changes[r]||'';err.hidden=true}
dlg.querySelectorAll('input[name="role-pick"]').forEach(function(i){i.onchange=show});srv.oninput=function(){err.hidden=true};
document.getElementById('role-change').onclick=function(){var cur=row.dataset.role||'solo';
dlg.querySelectorAll('input[name="role-pick"]').forEach(function(i){i.checked=i.value===cur});srv.value=row.dataset.server||'';nm.value=row.dataset.name||'';show();
dlg.hidden=false;nm.focus()};
document.getElementById('role-no').onclick=function(){dlg.hidden=true};dlg.addEventListener('keydown',function(e){if(e.key==='Escape'){e.stopPropagation();e.preventDefault();dlg.hidden=true}});
document.getElementById('role-yes').onclick=function(){var r=pick(),s=srv.value.trim(),n=nm.value.trim();
if(r==='roaming'&&!s){err.textContent='A laptop copy needs the name of the home server.';err.hidden=false;srv.focus();return}
var q={verb:'machine-role',role:r};if(r!=='solo'&&n)q.name=n;if(r==='roaming')q.server=s;
if(send(q))dlg.hidden=true}}
/* ---- the read guard ---- */
function was(el){return el.dataset.was}
if(rg){
rg.addEventListener('change',function(e){var i=e.target;if(!i.matches('input[type=radio]'))return;var r=i.closest('[data-rg]'),k=r.dataset.rg,q={verb:'read-guard'};
q[k]=i.value;if(!send(q)){var back=r.querySelector('input[value="'+was(r)+'"]');if(back)back.checked=true}});
rg.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
if(b.id==='rg-show'){var l=document.getElementById('rg-list');l.hidden=!l.hidden;b.setAttribute('aria-expanded',String(!l.hidden));return}
var key=b.dataset.rgAdd||b.dataset.rgRemove&&b.dataset.list;if(!key)return;var list=JSON.parse(rg.dataset[key]||'[]');
if(b.dataset.rgAdd){var inp=rg.querySelector('.rgnew[data-list="'+key+'"]'),v=inp.value.trim();
if(!/^[A-Za-z0-9_.*?-]{1,100}$/.test(v)||v.indexOf('..')>=0){if(said){said.hidden=false;said.className='hint rgsaid bad';said.textContent='A tool name is letters, numbers, dots, dashes, underscores and * or ? for a pattern.'}return}
if(list.some(function(x){return x.toLowerCase()===v.toLowerCase()}))return;list.push(v)}
else list=list.filter(function(x){return x!==b.dataset.rgRemove});
var q={verb:'read-guard'};q[key]=list;send(q)})}
var prev=window.GarrickActed;window.GarrickActed=function(q,out){
if(q&&(q.verb==='machine-role'||q.verb==='read-guard')){pending=null;tell(out||{ok:false,say:'That did not work.'});
if(!(out&&out.ok)&&rg)rg.querySelectorAll('[data-rg][data-was]').forEach(function(r){var b=r.querySelector('input[value="'+was(r)+'"]');if(b)b.checked=true});
return}
if(prev)return prev(q,out)};
})();
"""
