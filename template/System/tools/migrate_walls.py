#!/usr/bin/env python3
"""Turn a workspace's Walls table into a flag on each party, and show what that changes first.

Garrick 0.60.0 moved the walls from pairs of parties to one flag on each party:
a walled party's material goes only into work that names it, an open party's
goes anywhere. `update.py` runs this once, when the Parties table of
`System/context.md` has no Walled column. It does three things:

1. Proposes the flags: every party with a row in the Walls table is walled,
   every other one open (a party of the Projects zone, which holds the user's
   own ventures, is proposed open: those are published); each zone's Party and
   New parties columns.
2. Diffs the workspace, not the parties. Every labelled record (Meetings pages,
   raw records, inbox mail) and every project and thread note is run through
   the policy the Walls table writes and through the one the flags write, for
   read, write and file, into every project scope. Each flow whose verdict
   changes is printed, grouped, with one example path each. A diff over pairs
   of parties could not see a change that only appears on a combined label set.
3. Writes only on a yes: the columns go in, the Walls table goes out, and the
   whole workspace is checked. Until then nothing is written.

The policy the Walls table wrote is kept here under names that start with
`legacy_`: this module is the only place it lives.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LEGACY_PUBLIC = "public"
ACTIONS = ("read", "write", "file")
OPEN_ZONE = "projects"          # the zone of the user's own, published ventures
OWN_LABEL = "Own affairs"       # what a party named after the owner is called instead: what it holds


# ---------------------------------------------------------------------------
# The policy the Walls table wrote (v0.59.1's decide(), with its pairs reader)
# ---------------------------------------------------------------------------

def legacy_pairs(root, lib):
    """The pairs in the Walls table of System/context.md: a set of frozensets of two tags."""
    try:
        text = (Path(root) / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    pairs = set()
    for row in lib._table(lib._sections(text).get("walls", [])):
        cells = list(row.values())
        a = lib.strip_tag(row.get("between") or (cells[0] if cells else ""))
        b = lib.strip_tag(row.get("and") or (cells[1] if len(cells) > 1 else ""))
        if a and b:
            pairs.add(frozenset((a, b)))
    return pairs


def legacy_walled(context, tag_a, tag_b):
    if not tag_a or not tag_b or tag_a == tag_b:
        return False
    return frozenset((tag_a, tag_b)) in (context.get("walls") or context.get("pending") or set())


def _tags(value):
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {t for t in (str(v).strip().strip("`").lstrip("#").strip().lower() for v in value) if t}


def legacy_crossings(context, left, right=None):
    a = _tags(left)
    if right is None:
        return sorted((x, y) for x in a for y in a if x < y and legacy_walled(context, x, y))
    b = _tags(right)
    pairs = {(x, y) for x in a for y in b if legacy_walled(context, x, y)}
    if LEGACY_PUBLIC in a:
        pairs |= {(LEGACY_PUBLIC, y) for y in b if y in context.get("parties", {})}
    return sorted(pairs)


def legacy_decide(scope, labels, action, context, lib):
    """v0.59.1's decide(), word for word in what it answers."""
    known = set(context.get("parties", {})) - {"none", LEGACY_PUBLIC}
    mine = _tags(scope)
    if scope is not None and (mine - {LEGACY_PUBLIC}) - known:
        return "deny"
    if labels is None:
        return "deny" if action != "file" else "confirm"
    theirs = _tags(labels)
    if action == "read":
        if not theirs:
            return "deny"
        if theirs <= {LEGACY_PUBLIC}:
            return "permit"
        theirs -= {LEGACY_PUBLIC}
        mine -= {LEGACY_PUBLIC}
        if not theirs <= known or not mine:
            return "deny"
        return "deny" if legacy_crossings(context, mine, theirs) or legacy_crossings(context, theirs) \
            or legacy_crossings(context, mine) else "permit"
    if action == "write":
        if not mine:
            return "deny"
        if LEGACY_PUBLIC in mine:
            return "deny" if theirs - {LEGACY_PUBLIC} else "permit"
        theirs -= {LEGACY_PUBLIC}
        if not theirs <= known:
            return "deny"
        return "deny" if legacy_crossings(context, mine, theirs) or legacy_crossings(context, theirs) else "permit"
    if not theirs:
        return "confirm"
    if scope is not None and (not mine or legacy_crossings(context, mine, theirs - {LEGACY_PUBLIC})):
        return "deny"
    theirs -= {LEGACY_PUBLIC}
    if not theirs <= known:
        return "deny"
    if legacy_crossings(context, theirs) or any(lib.always_asked(context, t) for t in theirs):
        return "confirm"
    return "permit"


def legacy_blocked(context, scope, labels):
    """The tags in `labels` the old rule keeps out of a record whose parties are `scope`: those with a pair
    against one of them, and those paired with another tag of `labels`."""
    held, theirs = _tags(scope), _tags(labels)
    pairs = {t for t in theirs for s in held if legacy_walled(context, t, s)}
    return pairs | {t for t in theirs for o in theirs if legacy_walled(context, t, o)}


def legacy_project_labels(root, lib, parts, cache):
    """What labels() gave a file of a project before the flags: its hub's and its thread note's
    (a project folder, every thread's); a hub that names no party gave None."""
    project = Path(root) / "Zones" / parts[1] / parts[2]
    hub = ("legacy-hub", str(project))
    if hub not in cache:
        cache[hub] = lib._labels_of(lib.parse_frontmatter(project / (project.name + ".md")))
    found = cache[hub]
    if not found:
        return None
    out = set(found)
    if len(parts) >= 5 and parts[3] == "Threads":
        threads = [parts[4]]
    elif len(parts) <= 3:
        threads = sorted(p.name for p in (project / "Threads").glob("*/"))
    else:
        threads = []
    for t in threads:
        got = lib._labels_of(lib.parse_frontmatter(project / "Threads" / t / (t + ".md")))
        if got is None:
            return None
        out |= got
    return frozenset(out)


# ---------------------------------------------------------------------------
# The proposal
# ---------------------------------------------------------------------------

def pending(root, lib):
    """Does the Parties table of System/context.md still lack its Walled column?"""
    try:
        text = (Path(root) / "System" / "context.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    header = lib._table_header(lib._sections(text).get("parties", []))
    return bool(header) and not any(h.startswith("walled") for h in header)


def _projects(root, lib):
    """{zone: {project: (hub tags or None, {thread: tags or None})}} for every project folder."""
    out = {}
    zones = Path(root) / "Zones"
    if not zones.is_dir():
        return out
    for zone in sorted(p for p in zones.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for project in sorted(p for p in zone.iterdir() if p.is_dir() and not p.name.startswith(".")
                              and p.name not in ("Inbox", "archive")):
            hub = lib.parse_frontmatter(project / (project.name + ".md"))
            threads = {}
            for t in sorted(p for p in (project / "Threads").glob("*/") if p.is_dir()):
                threads[t.name] = lib._labels_of(lib.parse_frontmatter(t / (t.name + ".md")))
            out.setdefault(zone.name, {})[project.name] = (lib._labels_of(hub), threads)
    return out


def propose(root, lib, ctx):
    """The flags and the zone columns the Walls table implies, as a dict:
    flags {tag: True when walled}, zone_party {zone: tag or ""}, zone_default {zone: "walled" | "open"},
    notes [what to tell the user], pairs the legacy pairs."""
    pairs = legacy_pairs(root, lib)
    in_walls = {t for pair in pairs for t in pair}
    parties = ctx["parties"]
    notes = []
    flags = {}
    for tag, row in parties.items():
        zone = row.get("zone", "")
        venture = zone.casefold() == OPEN_ZONE and tag in in_walls
        flags[tag] = tag in in_walls and not venture
        if venture:
            notes.append("`%s` is a party of the %s zone: proposed open, as its material is published." % (tag, zone))
    projects = _projects(root, lib)
    zones = list(ctx["zones"]) or sorted(projects)
    zone_party, zone_default = {}, {}
    for zone in zones:
        # a zone's party is the one named in the `party:` of more than half of its project hubs (the Projects zone,
        # which holds ventures, names none); it is proposed walled, since an open zone party labels nothing that matters
        hubs = [hub or set() for hub, _ in projects.get(zone, {}).values()]
        count = {}
        for hub in hubs:
            for tag in hub:
                count[tag] = count.get(tag, 0) + 1
        top = [t for t, n in count.items() if n * 2 > len(hubs) and t in parties]
        pick = top[0] if len(top) == 1 and zone.casefold() != OPEN_ZONE else ""
        zone_party[zone] = pick
        if pick and not flags.get(pick):
            flags[pick] = True
            notes.append("`%s` is the party of zone %s (named by most of its projects): proposed walled, as its "
                         "material stays in the zone." % (pick, zone))
    for zone in zones:
        mine = [t for t, r in parties.items() if (r.get("zone") or "").casefold() == zone.casefold()]
        zone_default[zone] = "walled" if not mine or sum(flags[t] for t in mine) * 2 > len(mine) else "open"
    for group in projects.values():
        for name, (hub, threads) in group.items():
            if LEGACY_PUBLIC in (hub or set()) or any(LEGACY_PUBLIC in (t or set()) for t in threads.values()):
                notes.append("project %s names the reserved tag `public`, which is no longer a party: it will "
                             "label nothing until its note names a party." % name)
    owner = ctx.get("owner")
    renames = {}
    taken = {(r.get("party") or "").strip().casefold() for r in parties.values()}
    for tag, row in parties.items():
        if owner and (row.get("party") or "").strip().casefold() == owner["name"].casefold():
            label = OWN_LABEL if OWN_LABEL.casefold() not in taken else "%s (%s)" % (OWN_LABEL, row.get("zone") or tag)
            n = 2
            while label.casefold() in taken:
                label = "%s (%s) %d" % (OWN_LABEL, row.get("zone") or tag, n)
                n += 1
            taken.add(label.casefold())
            renames[tag] = label
            notes.append("`%s` is named after you, %s. Its name would be read as a walled party's in every note that "
                         "says it, so it is proposed renamed to %s, a label of what it holds." % (tag, owner["name"], label))
    return {"flags": flags, "zone_party": zone_party, "zone_default": zone_default, "notes": notes,
            "pairs": pairs, "zones": zones, "renames": renames}


def proposed_context(ctx, prop):
    """The context dict as load_context() would give it once the proposal is written."""
    new = dict(ctx, pending=None)
    new["parties"] = {t: dict(r, walled=prop["flags"][t], flag="yes" if prop["flags"][t] else "no",
                              party=prop.get("renames", {}).get(t, r.get("party")))
                      for t, r in ctx["parties"].items()}
    new["zone_parties"] = {z: t for z, t in prop["zone_party"].items() if t}
    new["zone_default"] = dict(prop["zone_default"])
    return new


def say_proposal(prop, ctx):
    lines = ["The Zones table would read:", "", "| Zone | Party | New parties |", "|---|---|---|"]
    for z in prop["zones"]:
        lines.append("| %s | %s | %s |" % (z, "`%s`" % prop["zone_party"][z] if prop["zone_party"].get(z) else "",
                                          prop["zone_default"][z]))
    lines += ["", "The Parties table would carry:", "", "| Tag | Walled | Renamed to |", "|---|---|---|"]
    for t in sorted(prop["flags"]):
        lines.append("| `%s` | %s | %s |" % (t, "yes" if prop["flags"][t] else "no", prop.get("renames", {}).get(t, "")))
    for n in prop["notes"]:
        lines.append("")
        lines.append("Note: " + n)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The diff
# ---------------------------------------------------------------------------

def _rel(root, path):
    return Path(path).relative_to(root).as_posix()


def _entities(root, lib, ctx, new_ctx):
    """(sources, scopes): each a list of (example path, labels before, labels after), one per distinct
    pair of label sets. Sources are every labelled record and every project and thread note; scopes
    are the projects and their threads."""
    root = Path(root)
    cache_old, cache_new = {}, {}
    sources, scopes, seen_s, seen_c = [], [], set(), set()

    def add(out, seen, path, before, after):
        key = (before, after)
        if key not in seen:
            seen.add(key)
            out.append((_rel(root, path), before, after))

    def record(path):
        rel = path.relative_to(root)
        add(sources, seen_s, path, lib.labels(root, rel, ctx, cache_old), lib.labels(root, rel, new_ctx, cache_new))

    meetings = root / "Wikis" / "Meetings"
    for grade in ("", "dormant", "archive"):
        base = meetings / grade if grade else meetings
        for sub, pattern in (("wiki", "*.md"), ("raw", "*")):
            folder = base / sub
            if folder.is_dir():
                for path in sorted(folder.rglob(pattern)):
                    if path.is_file() and not path.name.startswith("."):
                        record(path)
    zones = root / "Zones"
    if zones.is_dir():
        for zone in sorted(p for p in zones.iterdir() if p.is_dir() and not p.name.startswith(".")):
            inbox = zone / "Inbox"
            if inbox.is_dir():
                for path in sorted(inbox.glob("*.eml")):
                    record(path)
    for zone, group in _projects(root, lib).items():
        for project, (_, threads) in group.items():
            base = ("Zones", zone, project)
            places = [base, base + (project + ".md",)] + \
                [base + ("Threads", t, t + ".md") for t in threads]
            for parts in places:
                path = root.joinpath(*parts)
                is_folder = len(parts) == 3
                before = legacy_project_labels(root, lib, parts[:3] if is_folder else parts, cache_old)
                after = lib.labels(root, Path(*parts), new_ctx, cache_new)
                add(sources, seen_s, path, before, after)
                add(scopes, seen_c, path, before, after)
    return sources, scopes


def flows(root, lib, ctx, prop):
    """Every flow whose verdict changes, as a list of dicts."""
    new_ctx = proposed_context(ctx, prop)
    old_ctx = dict(ctx, walls=prop["pairs"])
    sources, scopes = _entities(root, lib, ctx, new_ctx)
    scopes = scopes + [("", None, None)]          # a project not yet chosen: only `file` asks it
    found = {}
    for sp, s_before, s_after in sources:
        for cp, c_before, c_after in scopes:
            for action in ACTIONS:
                if not cp and action != "file":
                    continue
                old = legacy_decide(c_before if cp else None, s_before, action, old_ctx, lib)
                new = lib.decide(c_after if cp else None, s_after, action, new_ctx)
                if old == new:
                    continue
                key = (old, new, s_before, s_after, c_before, c_after, bool(cp))
                entry = found.setdefault(key, {"old": old, "new": new, "actions": [], "source": sp,
                                               "scope": cp or "(a project not yet chosen)",
                                               "s_before": s_before, "s_after": s_after,
                                               "c_before": c_before, "c_after": c_after})
                entry["actions"].append(action)
    return sorted(found.values(), key=lambda e: (e["old"], e["new"], e["source"], e["scope"]))


KINDS = (("deny", "permit", "Refused today, allowed after"),
         ("permit", "deny", "Allowed today, refused after"),
         ("permit", "confirm", "Allowed today, asked about after"),
         ("confirm", "permit", "Asked about today, allowed after"),
         ("deny", "confirm", "Refused today, asked about after"),
         ("confirm", "deny", "Asked about today, refused after"))


def _set(value):
    return "none" if value is None else (", ".join(sorted(value)) or "no party")


def say_flows(items):
    """The diff as text, grouped by kind, one example path each."""
    if not items:
        return "No flow in the workspace changes its verdict."
    out = ["%d flow%s change their verdict." % (len(items), "" if len(items) == 1 else "s")]
    for old, new, title in KINDS:
        group = [e for e in items if (e["old"], e["new"]) == (old, new)]
        if not group:
            continue
        out += ["", "%s (%d):" % (title, len(group))]
        for e in group:
            out.append("  %s: %s [%s] into %s [%s]" % ("/".join(e["actions"]), e["source"], _set(e["s_after"]),
                                                       e["scope"], _set(e["c_after"])))
            if (e["s_before"], e["c_before"]) != (e["s_after"], e["c_after"]):
                out.append("      labelled before as %s into %s" % (_set(e["s_before"]), _set(e["c_before"])))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------

def _section(lines, title):
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and l[3:].strip().lower() == title), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def _table_lines(lines, span):
    """(first, last + 1) of the first run of table lines inside `span`."""
    a, b = span
    first = next((i for i in range(a, b) if lines[i].lstrip().startswith("|")), None)
    if first is None:
        return None
    last = first
    while last < b and lines[last].lstrip().startswith("|"):
        last += 1
    return first, last


def _cells(line):
    return line.rstrip("\n").split("|")


def _add_column(lines, span, name, index_before, values, sep="---"):
    """Insert a column called `name` into the table in `span`, before the column whose header starts with one of
    `index_before` (else last), with `values(cells)` for each row. Edits the lines in place."""
    run = _table_lines(lines, span)
    if not run:
        return False
    first, last = run
    header = _cells(lines[first])
    names = [c.strip().lower() for c in header[1:-1]]
    at = next((i for i, n in enumerate(names) if any(n.startswith(b) for b in index_before)), len(names))
    for i in range(first, last):
        cells = _cells(lines[i])
        inner = cells[1:-1]
        inner += [" "] * (len(names) - len(inner))
        if i == first:
            cell = " %s " % name
        elif set("".join(inner)) <= set("-: "):
            cell = sep
        else:
            cell = " %s " % values(dict(zip(names, (c.strip() for c in inner))))
        inner.insert(at, cell)
        lines[i] = "|" + "|".join(inner) + "|"
    return True


def _rename_parties(lines, span, renames):
    """Put each new name in the Party cell of the row whose tag is a key of `renames`, keeping bold."""
    run = _table_lines(lines, span) if renames else None
    if not run:
        return
    first, last = run
    names = [c.strip().lower() for c in _cells(lines[first])[1:-1]]
    name_at = next((i for i, n in enumerate(names) if n.startswith("party")), None)
    tag_at = next((i for i, n in enumerate(names) if n.startswith("tag")), None)
    if name_at is None or tag_at is None:
        return
    for i in range(first + 2, last):
        cells = _cells(lines[i])
        inner = cells[1:-1]
        if len(inner) <= max(name_at, tag_at):
            continue
        tag = inner[tag_at].strip().strip("`#").lower()
        if tag in renames:
            bold = inner[name_at].strip().startswith("**")
            inner[name_at] = " %s " % ("**%s**" % renames[tag] if bold else renames[tag])
            lines[i] = "|" + "|".join(inner) + "|"


def rewrite(text, prop):
    """context.md with the columns in and the Walls table out. None when there is no Parties table."""
    lines = text.splitlines()
    parties = _section(lines, "parties")
    if parties is None or _table_lines(lines, parties) is None:
        return None
    # the Zones table first: it stands before Parties, so the later edit leaves its lines where they are
    zones = _section(lines, "zones")
    if zones is not None and _table_lines(lines, zones):
        header = [c.strip().lower() for c in _cells(lines[_table_lines(lines, zones)[0]])[1:-1]]
        if not any(h.startswith("party") for h in header):
            def zone_party(row):
                tag = prop["zone_party"].get(row.get("zone", ""), "")
                return "`%s`" % tag if tag else ""
            _add_column(lines, zones, "Party", ("learned",), zone_party)
            zones = _section(lines, "zones")
        header = [c.strip().lower() for c in _cells(lines[_table_lines(lines, zones)[0]])[1:-1]]
        if not any(h.startswith("new parties") for h in header):
            _add_column(lines, zones, "New parties", ("learned",),
                        lambda row: prop["zone_default"].get(row.get("zone", ""), "walled"))
    parties = _section(lines, "parties")
    _rename_parties(lines, parties, prop.get("renames") or {})
    _add_column(lines, parties, "Walled", ("domains", "learned"),
                lambda row: "yes" if prop["flags"].get(row.get("tag", "").strip("` ").lower(), True) else "no")
    walls = _section(lines, "walls")
    if walls is not None:
        a, b = walls
        while a > 0 and not lines[a - 1].strip():
            a -= 1
        del lines[a:b]
        if a < len(lines) and a > 0:
            lines.insert(a, "")
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def walls_check(root):
    """What the whole-workspace walls check finds now: [message]; the check could not run: ["..."]."""
    tool = Path(root) / "System" / "tools" / "check.py"
    try:
        r = subprocess.run([sys.executable, str(tool), "--root", str(root), "--walls-only", "--json"],
                           capture_output=True, text=True, timeout=1800)
        import json
        found = json.loads(r.stdout).get("findings", [])
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return ["the walls check could not run: %s" % exc]
    return ["%s: %s" % (f.get("path"), f.get("message")) for f in found if f.get("severity") in ("error", "warning")]


def refused_with(root, prop):
    """What the walls check, as it stands, refuses in the workspace once the proposed flags are written: [message].
    It runs on a temporary workspace of links to the real folders, with a copy of System/context.md that holds the
    flags, so nothing is written here. Names are in it, not only the verdicts of labelled records. It runs the
    check.py that ships beside this file, the Garrick being installed, so a report agrees with what the write
    then checks. The check could not run: None, which is not the same as no file."""
    root = Path(root)
    tool = Path(__file__).resolve().parent / "check.py"
    path = root / "System" / "context.md"
    try:
        text = rewrite(path.read_text(encoding="utf-8"), prop)
    except OSError:
        return None
    if text is None or not tool.is_file():
        return None
    tmp = Path(tempfile.mkdtemp(prefix="garrick-walls-")).resolve()
    try:
        for entry in root.iterdir():
            if entry.name == "System":
                (tmp / "System").mkdir()
                for child in entry.iterdir():
                    if child.name != "context.md":
                        (tmp / "System" / child.name).symlink_to(child)
            elif entry.name != ".git":
                (tmp / entry.name).symlink_to(entry)
        (tmp / "System" / "context.md").write_text(text, encoding="utf-8")
        r = subprocess.run([sys.executable, str(tool), "--root", str(tmp), "--walls-only", "--json"],
                           capture_output=True, text=True, timeout=1800)
        found = json.loads(r.stdout).get("findings", [])
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return sorted({"%s: %s" % (f.get("path"), f.get("message")) for f in found if f.get("severity") in ("error", "warning")})


def say_refused(found):
    if found is None:
        return "The walls check could not run, so the files these flags would refuse are not known. Run System/tools/check.py --walls-only after."
    if not found:
        return "The walls check, run with these flags, refuses no file."
    out = ["The walls check, run with these flags, would refuse %d thing%s that is committed today (a name in a note "
           "counts, not only a label):" % (len(found), "" if len(found) == 1 else "s")]
    out += ["  " + f for f in found[:50]]
    if len(found) > 50:
        out.append("  ... and %d more." % (len(found) - 50))
    return "\n".join(out)


def study(root, lib, refused=True):
    """Everything the user is shown before a yes: {"prop", "items", "refused", "text"}; None when nothing is pending.
    `refused` False skips the whole-workspace check, which can take several minutes on a large workspace: "refused"
    is then None and the text says nothing of it."""
    if not pending(root, lib):
        return None
    ctx = lib.load_context(root)
    prop = propose(root, lib, ctx)
    items = flows(root, lib, ctx, prop)
    found = refused_with(root, prop) if refused else None
    text = "\n".join([
        "Walls are now a flag on each party (walled or open), not pairs of parties.",
        "", say_proposal(prop, ctx), "", say_flows(items)] + (["", say_refused(found)] if refused else []))
    refused = found
    return {"prop": prop, "items": items, "refused": refused, "text": text}
