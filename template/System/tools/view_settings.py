#!/usr/bin/env python3
"""view_settings.py: what Settings shows, as one document (#650).

The App's Settings dialog reads a good deal of the workspace: the choices it keeps, the fade settings, the notification
switches, the channels, the read guard's state and log, the preview flags, this computer's role. Until 0.79.0 the page
(`extras/status/status.py`) read each one for itself while it drew the dialog. This module is the one reader: it reads
the same files the page read, writes nothing, and `status.py` only draws what it returns.

`read(root)` returns the document; `view.settings()` is the way the page calls it. It is not part of `view.build()`:
Settings is the page's own, never scoped to a zone, and it names every zone's walled flag, so it never rides in a
document built for one zone.

A few readers belong to the status extra (the channels, the Telegram receiver's state, the held actions, the read
guard's settings reader, this computer's role). They stay where they are; this module loads them from `extras`, the
folder the page runs from, and a reader that cannot be loaded leaves its field `None`, so the section draws as it does
when that module is missing. What stays with the page, because it is this Mac's and no workspace's: the apps installed,
the launchd agents (the page hands them in, for the notice rows), whether cmux is here.

Standard library only.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

sys.dont_write_bytecode = True

API = 1
PARTS = ("desk", "flags", "release", "usage", "walls", "notifications", "channels", "memory", "guard", "machine")
HERE = Path(__file__).resolve().parent
DESK_AGENTS = ("claude", "codex")

# The jobs that send a row's notice, by the name their plist runs them under (job.py <name>): the todo sweep's morning
# summary, and the nightly job's Context digest.
NOTIFY_JOBS = {"todo-summary": (("gr-todo-sweep", "todo-sweep"), "the todo sweep"),
               "context-summary": (("gr-nightly", "nightly"), "the nightly job")}

_MODS: Dict[tuple, object] = {}


def _load(path: Path, name: str, need=()):
    """A module by its file, loaded once for as long as the file does not change; None when it is missing, does not load,
    or lacks a name in `need`."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _MODS:
        mod = None
        try:
            spec = importlib.util.spec_from_file_location(name, str(path))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod          # a dataclass in it looks its module up by name
            try:
                spec.loader.exec_module(mod)
            except BaseException:
                sys.modules.pop(name, None)
                raise
        except Exception:
            mod = None
        _MODS[key] = mod
    mod = _MODS[key]
    return mod if mod is not None and all(hasattr(mod, n) for n in need) else None


def own_lib(root: Path):
    """The workspace's own garrick_lib, from System/tools, the parser check.py uses; None when it is not there."""
    mod = _load(Path(root) / "System" / "tools" / "garrick_lib.py", "garrick_settings_own_lib", ("parse_frontmatter",))
    return mod if callable(getattr(mod, "parse_frontmatter", None)) else None


def prefs_lib(root: Path):
    """The garrick_lib that keeps the choices: the workspace's own, else the one beside this file."""
    for src in (Path(root) / "System" / "tools" / "garrick_lib.py", HERE / "garrick_lib.py"):
        mod = _load(src, "garrick_settings_prefs_lib")
        if mod is not None and callable(getattr(mod, "preferences", None)) and callable(getattr(mod, "save_preferences", None)):
            return mod
    return None


def notify_lib(root: Path):
    """System/tools/notifications.py: the workspace's own, else the one beside this file."""
    for src in (Path(root) / "System" / "tools" / "notifications.py", HERE / "notifications.py"):
        mod = _load(src, "garrick_settings_notifications")
        if mod is not None and callable(getattr(mod, "settings", None)) and hasattr(mod, "EVENTS"):
            return mod
    return None


def _extra(extras: Optional[Path], name: str, need=()):
    """A module of the status extra, by name, from the folder the page runs from."""
    if extras is None:
        return None
    return _load(Path(extras) / (name + ".py"), "garrick_settings_" + name, need)


def _shown(path: Path, root: Path) -> str:
    """A path as the document carries it: from the workspace when it is inside it, as it stands otherwise."""
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- the small readers

def desk_agent(root: Path) -> str:
    """The assistant a new cmux tab starts, as the desk reads it: `agent` in System/desk.json, or the file GARRICK_DESK_CONFIG
    names; claude when it is not set or the file does not read."""
    f = Path(os.environ.get("GARRICK_DESK_CONFIG") or Path(root) / "System" / "desk.json").expanduser()
    try:
        agent = json.loads(f.read_text(encoding="utf-8")).get("agent")
    except (OSError, ValueError, AttributeError):
        agent = None
    return agent if agent in DESK_AGENTS else "claude"


def preview_flags(root: Path) -> Dict[str, bool]:
    """System/garrick-flags.json: each flag it names and whether it is on (true, and nothing else, is on)."""
    try:
        data = json.loads(Path(root).joinpath("System", "garrick-flags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {str(k): v is True for k, v in data.items()}


def installed_line(root: Path) -> Optional[str]:
    """Which Garrick the workspace came from, in the words `check.py --version` uses, from the installer's stamp; None where
    the workspace's tools cannot say."""
    lib = own_lib(root)
    read, say = getattr(lib, "read_version", None), getattr(lib, "say_version", None)
    if not (callable(read) and callable(say)):
        return None
    try:
        stamp = read(root)
        said = [say(stamp)]
        changes = getattr(lib, "say_changes", None)
        if callable(changes):
            said.append(changes(root, stamp))
        return " ".join(s for s in said if s) or None
    except Exception:
        return None


def release(root: Path) -> dict:
    """About Garrick: the release the workspace runs (`number`, "" where unknown), the line `check.py --version` gives
    (`installed`, None where unknown), whether the check for a newer Garrick is on and its cadence in days (off and daily
    where it cannot be read), and a band kept outside the workspace from another commit (`stale`)."""
    lib = own_lib(root)
    read = getattr(lib, "workspace_release", None)
    try:
        number = str(read(root) or "") if callable(read) else ""
    except Exception:
        number = ""
    on, every = getattr(lib, "release_notice_on", None), getattr(lib, "release_every", None)
    try:
        choice = (bool(on(root)) if callable(on) else False, 7 if callable(every) and every(root).days == 7 else 1)
    except Exception:
        choice = (False, 1)
    found = getattr(lib, "stale_bands", None)
    try:
        stale = [str(x) for x in (found(root) if callable(found) else [])]
    except Exception:
        stale = []
    return {"number": number, "installed": installed_line(root), "notice_on": choice[0], "notice_every": choice[1], "stale": stale}


def usage_on(root: Path) -> bool:
    """Whether the App counts which cards are opened (#651): on unless the settings say false."""
    lib = prefs_lib(root)
    try:
        return (lib.preferences(root) if lib is not None else {}).get("usage-counts") is not False
    except Exception:
        return True


def walls(root: Path) -> dict:
    """Each zone's walled flag as System/context.md gives it, and whether they are still read from the Parties and Zones
    tables (the update to zone walls is not accepted yet)."""
    lib = own_lib(root)
    try:
        ctx = lib.load_context(root) if lib is not None and callable(getattr(lib, "load_context", None)) else {}
    except Exception:
        ctx = {}
    return {"flags": {str(z): bool(v) for z, v in (ctx.get("zone_walled") or {}).items()}, "pending": bool(ctx.get("pending"))}


def own_way(lib, jobs: Optional[Dict[str, dict]]) -> Dict[str, str]:
    """Event -> a plain sentence, for each row whose job's launchd plist sets GARRICK_NOTIFY or GARRICK_NOTIFY_CMD: that job
    sends its notice its own way, past the switch, so the row says where it goes and its box is not in use."""
    out: Dict[str, str] = {}
    try:
        jobs_ = jobs or {}
        over = getattr(lib, "override", None)
        for event, (names, said) in NOTIFY_JOBS.items():
            job = next((jobs_[n] for n in names if n in jobs_), {})
            env = {str(k): str(v) for k, v in (job.get("env") or {}).items()}
            kinds = over(env) if callable(over) else ()
            if kinds:
                out[event] = ("Sent by %s to the command you set, not by this switch." if "GARRICK_NOTIFY_CMD" in kinds
                              else "Sent by %s as its own Mac notice, not by this switch.") % said
    except Exception:
        return {}
    return out


def notifications(root: Path, jobs: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    """The six notices and their switches, the minutes a long task takes, quiet hours (notifications.py), and which rows a
    job sends its own way. None where notifications.py is not there."""
    lib = notify_lib(root)
    if lib is None or not hasattr(lib, "TELL"):
        return None
    try:
        cfg = lib.settings(root)
    except Exception:
        return None
    return {"settings": cfg, "tell": [[e, label] for e, label in lib.TELL], "after_max": lib.AFTER_MAX, "own_way": own_way(lib, jobs)}


def machine(root: Path, extras: Optional[Path]) -> dict:
    """This computer's role, its name and the home server's, as machine.py reads them: one computer with no name where
    there is no role file."""
    box = _extra(extras, "outbox")
    try:
        mod = box._machine(root) if box else None
        rec = mod.read() if mod else {}
        return {"role": str(rec.get("role") or "solo"), "name": str(rec.get("name") or ""), "server": str(rec.get("server") or "")}
    except Exception:
        return {"role": "solo", "name": "", "server": ""}


def channels(root: Path, extras: Optional[Path]) -> Optional[dict]:
    """Ask's and Telegram's tier, effort and autonomy, what the last capability check found, the Telegram receiver's state
    line, and the actions waiting for a yes. None where the channels cannot be read."""
    ch = _extra(extras, "channels", ("settings", "kept", "CHANNELS"))
    if ch is None:
        return None
    try:
        cfg = ch.settings(root)
        cap = ch.kept() or {"ok": True}
    except Exception:
        return None
    out = {"settings": cfg, "capability": cap, "names": list(ch.CHANNELS), "tiers": list(ch.TIERS), "efforts": list(ch.EFFORTS),
           "levels": {c: list(ch.LEVELS_FOR[c]) for c in ch.CHANNELS}, "telegram": None, "held": None}
    state = _extra(extras, "channel_state", ("row",))
    try:
        out["telegram"] = state.row() if state else None
    except Exception:
        out["telegram"] = None
    hold = _extra(extras, "hold", ("listing",))
    try:
        out["held"] = list(hold.listing()) if hold else None
    except Exception:
        out["held"] = None
    return out


@contextlib.contextmanager
def _tools_path(root: Path):
    """The workspace's System/tools/ first on the path while fade.py is loaded or asked, as it would be run there; the path
    and the modules it imported put back after, so nothing of one workspace stays for another."""
    path, before = list(sys.path), set(sys.modules)
    sys.path.insert(0, str(Path(root) / "System" / "tools"))
    try:
        yield
    finally:
        sys.path[:] = path
        for k in set(sys.modules) - before:
            sys.modules.pop(k, None)


def fade_lib(root: Path):
    """The workspace's own System/tools/fade.py; None when there is none, it does not load, or it lacks settings() and counts()."""
    src = Path(root) / "System" / "tools" / "fade.py"
    if not src.is_file():
        return None
    try:
        key = (str(src), src.stat().st_mtime_ns, "fade")
    except OSError:
        return None
    if key not in _MODS:
        mod = None
        name = "garrick_settings_fade"
        try:
            with _tools_path(root):
                spec = importlib.util.spec_from_file_location(name, str(src))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod             # its dataclasses look their module up by name
                spec.loader.exec_module(mod)
            if not (callable(getattr(mod, "settings", None)) and callable(getattr(mod, "counts", None))):
                mod = None
        except Exception:
            mod = None
        _MODS[key] = mod
    return _MODS[key]


def memory(root: Path, wikis: Iterable[str] = ("Meetings", "Knowledge")) -> Optional[dict]:
    """How older material fades: fade.py's settings and counts for each wiki, its two sentences (`age_said`, `wake_said`),
    and each wiki's full list where the last review wrote one. `error` names the kind of fault when fade.py gave no
    settings. None where fade.py is not there."""
    lib = fade_lib(root)
    if lib is None:
        return None
    out = {"age_said": getattr(lib, "AGE_SAID", None), "wake_said": getattr(lib, "WAKE_SAID", None), "error": None,
           "settings": None, "counts": None, "full_list": {}}
    try:
        with _tools_path(root):
            out["settings"] = lib.settings(root)
            out["counts"] = lib.counts(root)
        cfg = out["settings"]
        cfg["wikis"], cfg["kinds"], cfg["pins"]          # the keys the section reads
    except Exception as e:
        out["error"] = type(e).__name__
        out["settings"] = out["counts"] = None
        return out
    paths = getattr(lib, "proposal_paths", None)
    for w in wikis:
        if w not in out["counts"]:
            continue
        path = paths(root, w)[0] if callable(paths) else Path(root) / "System" / "generated" / "fade" / ("%s.md" % w)
        if Path(path).is_file():
            out["full_list"][w] = _shown(Path(path), Path(root))
    return out


def guard(root: Path, extras: Optional[Path]) -> Optional[dict]:
    """The read guard as Settings shows it: whether its hook is registered, its mode and cross-wall choice, both tool lists,
    whether the connector filter can run, and what its log holds from the last week, as settings_guard.py reads them
    (`state`; each line's time as ISO text); and whether the assistant here is Codex. None where it cannot be read."""
    sg = _extra(extras, "settings_guard", ("read_state", "guard_block"))
    lib = prefs_lib(root)
    if sg is None or lib is None:
        return None
    try:
        state = sg.read_state(root, lib)
    except Exception:
        return None
    would = {z: [dict(i, when=i["when"].isoformat() if isinstance(i.get("when"), dt.datetime) else i.get("when")) for i in items]
             for z, items in (state.get("would") or {}).items()}
    ch = _extra(extras, "channels", ("assistant",))
    try:
        codex = ch.assistant() == "codex" if ch else False
    except Exception:
        codex = False
    return {"state": dict(state, would=would), "codex": codex}


# --------------------------------------------------------------------------- the document

def read(root, extras: Optional[Path] = None, jobs: Optional[Dict[str, dict]] = None, only: Optional[Iterable[str]] = None) -> dict:
    """What Settings shows, as one JSON-serialisable document. `extras` is the folder of the status extra; `jobs` this Mac's
    launchd agents as the page reads them (the notice rows need their environment); `only` names the parts to read, from
    `PARTS`, and a part not asked for is left out and not read. Reads; never writes."""
    root = Path(root)
    parts = set(PARTS) if only is None else set(only)
    out: dict = {"api": API}
    if "desk" in parts:
        out["desk_agent"] = desk_agent(root)
    if "flags" in parts:
        out["flags"] = preview_flags(root)
    if "release" in parts:
        out["release"] = release(root)
    if "usage" in parts:
        out["usage_counts"] = usage_on(root)
    if "walls" in parts:
        out["walls"] = walls(root)
    if "notifications" in parts:
        out["notifications"] = notifications(root, jobs)
    if "channels" in parts:
        out["channels"] = channels(root, extras)
    if "memory" in parts:
        out["memory"] = memory(root)
    if "machine" in parts or "guard" in parts:
        out["machine"] = machine(root, extras)
    if "guard" in parts:
        out["read_guard"] = guard(root, extras)
    return out
