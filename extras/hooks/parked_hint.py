#!/usr/bin/env python3
"""The parked-thread hint: a Claude Code hook that tells a session when a request may belong to a thread that is parked.

A parked thread's memory pointer leaves the memory index until the thread is woken (#664), so a session no longer
sees it and cannot notice that a request is about it. This hook gives that back, for the cost of one line.

It runs on UserPromptSubmit and reads the prompt. It matches whole words of the prompt, in any case, against each
parked thread's name and its `spoken:` form (any word of four letters or more that is not on the short list below),
its hub's `party:` tag and the full names of that party's people (as a phrase). A request about a thread's subject
rarely repeats its whole name, so one word of the name is enough; a short word or a common one never matches alone.
At most the best two are named, the most matched words first. On a match it adds one line of context:

    This may belong to *Acme, Pricing*, which is parked: say 'wake Acme, Pricing' to pick it up.

With no match it adds nothing. It adds nothing, too, when the workspace has no `memory` setting (then no pointer
ever left an index), when the session is not in a workspace, and on any error: a broken hint must not stop a session.

The walls. It names a thread of the session's own zone, or of an open zone. A session at the workspace root or in
System/, which the zone guard treats as zone-free, may be told of a thread of any zone. A session in a wiki, or in
any other folder, is told of open zones only. It never names a parked thread of another walled zone and never says
that one exists: no count, no hint that some are hidden. The cache keeps names, zones and statuses of every zone, in
System/generated/parked-hints.json, which git leaves out; what the session is told is filtered after it is read.

The cost. It lists the hub and thread notes by name and reads their frontmatter only when a note's modification
time has changed since the cache was written. It writes nothing of the prompt anywhere: not in the cache, not in a
log, not in an error. It ends well inside the 5 seconds the registration allows.

Register it for Claude Code in the `hooks` block of ~/.claude/settings.json (extras/hooks/README.md has the block).
Python 3.9+, standard library only.
"""
import json
import os
import re
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

zg = None     # zone_guard, imported inside main()'s try: a hook that cannot load it adds nothing

CACHE = ("System", "generated", "parked-hints.json")
CACHE_VERSION = 1
MOST = 2                      # names in one line
# A word that never matches alone: too common in a thread's name to say what a request is about.
STOP = frozenset("""a an and are as at be by do for from have how i in is it me my of on or our so that the this to
us we with you new old plan note notes draft review work project projects thread threads meeting email update
status next open send call help""".split())


def words(text):
    """The lower-case words of a text: letters and digits, with an apostrophe or an ampersand inside a word."""
    return re.findall(r"[^\W_]+(?:['&][^\W_]+)*", text.lower())


def keys_of(*texts):
    """Each text as a phrase of words, as a tuple; a single word of one or two letters, or on the STOP list,
    is left out."""
    out = []
    for text in texts:
        w = tuple(words(str(text or "")))
        if not w or (len(w) == 1 and (len(w[0]) < 3 or w[0] in STOP)):
            continue
        if w not in out:
            out.append(w)
    return out


def significant(*texts):
    """The words of a thread's name or spoken form that may match a prompt alone: four letters or more, and not on
    the STOP list. A request about a thread's subject rarely repeats its whole name."""
    return {w for text in texts for w in words(str(text or "")) if len(w) >= 4 and w not in STOP}


def contains(prompt_words, key):
    n = len(key)
    return any(tuple(prompt_words[i:i + n]) == key for i in range(len(prompt_words) - n + 1))


def note_paths(root):
    """[(path from the root, modification time in ns)] of every hub and thread note, by listing folders only. A
    project or thread folder whose real place is not inside its own zone's is skipped (a link into another zone
    would give that zone's work under this one's name); one that leaves the workspace altogether may stay."""
    out = []
    zones = os.path.join(root, "Zones")
    base = os.path.realpath(root)

    def kept(path, zone_real):
        real = os.path.realpath(path)
        inside = lambda b, p: p == b or p.startswith(b + os.sep)
        return inside(zone_real, real) or not inside(base, real)

    for zone in sorted(os.listdir(zones)):
        zdir = os.path.join(zones, zone)
        if zone.startswith((".", "_")) or not os.path.isdir(zdir):
            continue
        zone_real = os.path.realpath(zdir)
        for project in sorted(os.listdir(zdir)):
            pdir = os.path.join(zdir, project)
            if project.startswith((".", "_")) or project in ("Inbox", "archive") or not os.path.isdir(pdir) \
                    or not kept(pdir, zone_real):
                continue
            hub = os.path.join(pdir, project + ".md")
            if os.path.isfile(hub):
                out.append((hub, os.stat(hub).st_mtime_ns))
            threads = os.path.join(pdir, "Threads")
            if os.path.isdir(threads) and kept(threads, zone_real):
                for thread in sorted(os.listdir(threads)):
                    tdir = os.path.join(threads, thread)
                    note = os.path.join(tdir, thread + ".md")
                    if os.path.isfile(note) and kept(tdir, zone_real):
                        out.append((note, os.stat(note).st_mtime_ns))
    return [(os.path.relpath(p, root).replace(os.sep, "/"), m) for p, m in out]


def signature(root, notes):
    """What the cache was built from: each note's time, and the files the zones' flags and people are read from."""
    sig = [list(x) for x in notes]
    for name in ("context.md", "names.md"):
        path = os.path.join(root, "System", name)
        try:
            sig.append(["System/" + name, os.stat(path).st_mtime_ns])
        except OSError:
            pass
    return sig


def build(root, lib):
    """The cache's content: every parked thread, as names, zones and statuses. A parked project counts as one
    entry, since every thread in it is parked with it; a thread of a live project is one entry of its own."""
    notes = lib.work_notes(root)
    context = lib.load_context(root)
    people = {}
    for p in context.get("people") or []:
        tag = lib.strip_tag(p.get("party") or "")
        if tag and p.get("name"):
            people.setdefault(tag, []).append(p["name"])
    entries = []
    hubs = {(i["zone"], i["project"]): i for i in notes.values() if i["thread"] is None}
    for path, info in sorted(notes.items()):
        hub = hubs.get((info["zone"], info["project"]), {})
        if info["thread"] is None:
            if info["status"] != "parked":
                continue
            say, leaf, spoken = info["project"], info["project"], info["spoken"]
        else:
            if info["status"] != "parked" and hub.get("status") != "parked":
                continue
            if hub.get("status") == "parked":
                continue                                         # the project is the entry
            say, leaf, spoken = "%s, %s" % (info["project"], info["thread"]), info["thread"], info["spoken"]
        party = info.get("party") or hub.get("party") or []
        party = [lib.strip_tag(str(x)) for x in (party if isinstance(party, list) else [party]) if x]
        entries.append({"zone": info["zone"], "say": say, "name": leaf, "spoken": spoken, "party": party,
                        "people": sorted({n for tag in party for n in people.get(tag, [])})})
    walled = {z: bool(v) for z, v in (context.get("zone_walled") or {}).items()}
    return {"entries": entries, "walled": walled}


def load(root, lib, rebuild=False):
    """The cache, rebuilt when a note's time changed, when it does not read as a cache, or when `rebuild` is set."""
    notes = note_paths(root)
    sig = signature(root, notes)
    path = os.path.join(root, *CACHE)
    try:
        with open(path, encoding="utf-8") as f:
            have = json.load(f)
        if not rebuild and isinstance(have, dict) and have.get("version") == CACHE_VERSION \
                and have.get("signature") == sig and isinstance(have.get("entries"), list) \
                and isinstance(have.get("walled"), dict):
            return have
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    have = dict(build(root, lib), version=CACHE_VERSION, signature=sig)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".ph-", dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(have, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return have


def home_of(event):
    given = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd")
    return os.path.realpath(given) if given else None


def zones_told(root, home, walled):
    """The zones a session at `home` may be told of: every zone for a session the zone guard treats as zone-free
    (the root, System/), its own zone and the open ones from a zone or a project, only the open ones from anywhere
    else, a wiki included. A zone the Zones table does not list counts as walled."""
    blind = zg.case_blind(root)
    names = zg.parts(root, home, blind)
    if names is None:
        return set()
    open_zones = {z for z, w in walled.items() if not w}
    if not names or names[0] == "System":
        return set(walled)
    if names[0] == "Zones" and len(names) >= 2:
        return open_zones | {names[1]}
    return open_zones


def hint(prompt, entries, told):
    """The line to add, or "" for no match. Only entries of a zone in `told` are looked at, so a name outside it is
    never read against the prompt, let alone said."""
    pw = words(prompt)
    if not pw:
        return ""
    seen = set(pw)
    found = []
    for e in entries:
        if e["zone"] not in told:
            continue
        score = 2 * len(significant(e["name"], e.get("spoken")) & seen)
        if any(contains(pw, k) for k in keys_of(*e.get("party", []))):
            score += 1
        if any(contains(pw, k) for k in keys_of(*[n for n in e.get("people", []) if len(words(n)) > 1])):
            score += 1
        if score:
            found.append((-score, e["say"]))
    if not found:
        return ""
    found.sort()
    best = [say for s, say in found][:MOST]            # most matched words first
    if len(best) == 1:
        return "This may belong to *%s*, which is parked: say 'wake %s' to pick it up." % (best[0], best[0])
    names = ", ".join("*%s*" % s for s in best[:-1]) + " or *%s*" % best[-1]
    return "This may belong to %s, which are parked: say 'wake' and the name to pick one up." % names


def run(event):
    """The hook's reply for an event, or None for nothing."""
    if event.get("hook_event_name") not in (None, "UserPromptSubmit"):
        return None
    prompt = event.get("prompt")
    home = home_of(event)
    if not isinstance(prompt, str) or not home:
        return None
    root = zg.workspace_root(home)
    if root is None:
        return None
    tools = os.path.join(root, "System", "tools")
    if tools not in sys.path:
        sys.path.insert(1, tools)
    import garrick_lib as lib
    if not lib.memory_folders(root):                    # no memory setting: no pointer ever left an index
        return None
    try:
        have = load(root, lib)
        line = hint(prompt, have["entries"], zones_told(root, home, have["walled"]))
    except (AttributeError, TypeError, KeyError):         # a cache that read but does not fit: made again
        have = load(root, lib, rebuild=True)
        line = hint(prompt, have["entries"], zones_told(root, home, have["walled"]))
    if not line:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": line}}


def main():
    try:
        global zg
        import zone_guard as zg  # noqa: E402
        event = json.loads(sys.stdin.read() or "{}")
        reply = run(event) if isinstance(event, dict) else None
        if reply:
            sys.stdout.write(json.dumps(reply))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
