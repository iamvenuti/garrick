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
so is never listed, never counted and never offered as a pick. The page is one
static file, as status.py's always is (it holds every zone's projects, todos
and Needs you questions, and the app picks the zone): every bucket is in the
page source and the script shows one. What a bucket holds is only what is on
the near side of its own view. A wall finding is never shown here; the Checks
card says it in its own words. Everything the page draws from the data is text
(textContent), never markup, a link or a command.

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
ALL = "*"           # the choice that means every zone, or every party of a zone (#384)
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
        "writes": dict({"answer": [answer_file, qpath], "later": [qpath], "close": [qpath]},
                       **({"decide": [answer_file, "Wikis/%s/wiki/decisions/%s - %s.md" % (wiki, today.strftime("%y%m%d"), slug), qpath]}
                          if wiki == "Meetings" else {})),
        "verdict": verdict if verdict in VERDICTS else "",
        "reason": clip(q.fm.get("verdict_reason") or "", LINE_MAX) if verdict in VERDICTS else "",
    }


DECISION_STATES = ("valid", "superseded", "withdrawn")


def decision_files(ws: Path) -> List[str]:
    """Each decision page of the Meetings wiki, as a path from the wiki's
    folder, at any depth of wiki/decisions/; a link or hidden file is passed over."""
    pa = page_action()
    base = Path(ws) / "Wikis" / "Meetings" / Path(*pa.WIKI_DECISION_DIR)
    out = []
    if not base.is_dir() or base.is_symlink():
        return out
    for p in sorted(base.rglob("*.md")):
        parts = p.relative_to(base).parts
        if p.is_symlink() or not p.is_file() or pa.SKIP & set(parts) or any(x.startswith((".", "_")) for x in parts):
            continue
        out.append(p.relative_to(base.parent.parent).as_posix())
    return out


def read_decision(ws: Path, lib, rel: str, link: Callable) -> Optional[dict]:
    """One decision page as the panel lists it, with the tags the walls place
    it by, or None for a page whose frontmatter cannot be read plainly, that
    is not `type: decision`, or whose zone or parties are missing (fail
    closed: an unfinished page is placed nowhere)."""
    path = Path(ws) / "Wikis" / "Meetings" / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    pa = page_action()
    if lib.frontmatter_form_problem(text) or pa.party_keys_two_ways(text):
        return None
    fm = lib.parse_frontmatter_text(text)
    status = str(fm.get("status") or "").strip().lower()
    zone = fm.get("zone")
    tags = [pa.bare_tag(lib, t) for t in pa.tags_of(fm.get("parties"))]
    if fm.get("type") != "decision" or status not in DECISION_STATES or not isinstance(zone, str) or not zone.strip() or not tags:
        return None
    revisit = clip(fm.get("revisit") or "", LINE_MAX)
    return {"file": rel, "title": clip(fm.get("title") or path.stem, TITLE_MAX), "status": status,
            "decided": str(fm.get("decided") or "")[:10], "revisit": revisit, "zone": zone.strip(),
            "parties": sorted(tags), "href": link(path)}


def plain_party_keys(path: Path) -> bool:
    """False for a page that spells its party key two ways (`party:` and
    `PARTY:`), which a reader could take either way: it is placed nowhere."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        keys = _KEY_LINE.findall(re.match(r"---\n(.*?)\n---", text, re.S).group(1))
    except (OSError, UnicodeError, AttributeError):
        return False
    return all(k in ("party", "parties") for k in keys if k.lower() in ("party", "parties"))


_KEY_LINE = re.compile(r"(?m)^([A-Za-z_][\w-]*)\s*:")


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
            sorted_items += [N.sort_item(nctx, i, light=True) for i in N.check_items(f)]
        except Exception:
            continue
    # A page with a wall finding on it has no row: a save would be refused, and the Checks card says the wall.
    walled_paths = {i.path for i in sorted_items if i.kind == "wall" or pa.wallish(i.check, i.message)} | {w for i in sorted_items if i.kind == "wall" for w in i.where}
    for item in sorted_items:
        if item.kind not in ("attribution", "judgment") or item.key in seen or item.path in walled_paths:
            continue
        seen.add(item.key)
        put_off = later.get(item.key)
        if put_off and put_off["path"] == item.path and put_off["until"] > today.isoformat():
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
            if e is None or e["tagged"] or e["misread"] or e["parties"] or not plain_party_keys(path):
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
            if e["misread"] or not e["tagged"] or not e["parties"] or not view.ok(e["parties"]) or not plain_party_keys(e["path"]):
                continue
            names = [n for n in e["names"] if n not in (e["title"], e["rel"])]
            ents.append({"rel": e["rel"], "title": clip(e["title"], LINE_MAX), "aliases": [clip(n, LINE_MAX) for n in names[:6]]})
        out[key] = {"entities": ents, "parties": []}
    return out


def group_views(zones: List[dict], zone: str = ALL, party: str = ALL) -> List[dict]:
    """The groups the panel shows for a Zone and Party choice, *All* included (#384).

    `zones` is build()'s `zones` list. Each group is one view, exactly what
    0.56.0 shows for that zone and party: {"key": the bucket's key, "zone",
    "party" (a tag, or ""), "kind": "zone" | "party" | "unattributed",
    "heading": "Work · Acme Corp"}. A zone no wall divides is one group; a
    zone whose parties a wall divides is one group per party, or only the
    party chosen; the zone's unattributed entity pages come after its
    groups. A zone shown alone keeps 0.56.0's rule: a party that is not one of
    its own is read as its default. With a party chosen and All zones, only the
    zone that owns the party is shown. Order is the zones' own, then the parties'.
    Nothing here joins groups: it only lists them."""
    out: List[dict] = []
    for info in zones:
        name = info.get("zone")
        if zone != ALL and name != zone:
            continue
        scopes = info.get("scopes") or []
        tags = [sc["tag"] for sc in scopes]
        if not scopes:
            if party != ALL and zone == ALL:
                continue            # a party is chosen: a zone with no party menu does not own it
            out.append({"key": "%s|" % name, "zone": name, "party": "", "kind": "zone", "heading": name})
        else:
            if party == ALL:
                chosen = tags
            elif party in tags:
                chosen = [party]
            elif zone == ALL:
                continue
            else:
                chosen = [info.get("default") or tags[0]]
            for sc in scopes:
                if sc["tag"] in chosen:
                    out.append({"key": "%s|%s" % (name, sc["tag"]), "zone": name, "party": sc["tag"], "kind": "party",
                                "heading": "%s \u00b7 %s" % (name, sc.get("name") or sc["tag"])})
        if info.get("unattributed"):
            out.append({"key": "unattributed|%s" % name, "zone": name, "party": "", "kind": "unattributed",
                        "heading": "%s \u00b7 Unattributed" % name})
    return out


def can_sum(views: List[dict]) -> bool:
    """Whether one number may stand for these groups. Only when at most one
    holds parties: two groups may have a wall between them, and the page
    cannot show that they do not, so it fails closed and counts them apart.
    The unattributed group holds entity pages that name no party and the
    Knowledge group has none, so neither has a wall to cross."""
    return sum(1 for v in views if v["kind"] != "unattributed") <= 1


def selections(zones: List[dict]) -> Dict[str, dict]:
    """group_views for every Zone and Party choice the menus offer, keyed
    "zone|party" with All as *: {"views": [...], "sum": can_sum(views)}. The
    page looks a choice up here and does not work groups out itself."""
    zone_choices = [ALL] + [z["zone"] for z in zones]
    tags = [sc["tag"] for z in zones for sc in z.get("scopes") or []]
    out: Dict[str, dict] = {}
    for zc in zone_choices:
        own = tags if zc == ALL else [sc["tag"] for z in zones if z["zone"] == zc for sc in z.get("scopes") or []]
        for pc in [ALL] + own + ([] if zc == ALL else [""]):
            views = group_views(zones, zc, pc)
            out["%s|%s" % (zc, pc)] = {"views": views, "sum": can_sum(views)}
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
        info = {"zone": zone, "scopes": [], "default": "", "unattributed": False}
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
            info["unattributed"] = True
        except pa.Refused:
            pass
        if any(k.startswith(zone + "|") for k in views):
            zone_info.append(info)
    buckets: Dict[str, dict] = {k: {"questions": [], "answered": 0, "review": {"entities": [], "people": [], "read": []},
                                    "picks": {"entities": [], "parties": []}, "decisions": []} for k in views}
    knowledge, answered_k = [], 0
    # A question whose own file carries a walls-family finding is not listed: a save would be refused.
    wall_files = {re.sub(r":\d+$", "", str(f.get("path"))) for f in (C or {}).get("findings", [])
                  if isinstance(f, dict) and pa.wallish(f.get("check"), f.get("message"))}
    for wiki in WIKIS:
        for rel in question_files(ws, wiki):
            if "Wikis/%s/%s" % (wiki, rel) in wall_files:
                continue
            q = read_question(ws, wiki, rel, today, link)
            if q is None:
                continue
            if wiki == "Knowledge":
                if q["status"] == "answered":
                    answered_k += 1
                elif q["shown"]:
                    knowledge.append(q)
                continue
            for key, view in views.items():
                if key.startswith("unattributed|") or q["zone"] != view.zone or not view.ok(q["parties"]):
                    continue
                if q["status"] == "answered":
                    buckets[key]["answered"] += 1
                elif q["shown"]:
                    buckets[key]["questions"].append(q)
    # A decision page is placed as a question is: by its zone and parties, through the view's one test.
    # Only a valid decision with a revisit flag is listed (the assistant flags, the user settles).
    for rel in decision_files(ws):
        if "Wikis/Meetings/%s" % rel in wall_files:
            continue
        d = read_decision(ws, lib, rel, link)
        if d is None or d["status"] != "valid" or not d["revisit"]:
            continue
        for key, view in views.items():
            if not key.startswith("unattributed|") and d["zone"] == view.zone and view.ok(d["parties"]):
                buckets[key]["decisions"].append(d)
    for key, rows in review_rows(ws, nurture, C, lib, ctx, today, link, views).items():
        buckets[key]["review"] = rows
    for key, picks in pick_lists(ws, lib, views).items():
        buckets[key]["picks"] = picks
    # the menu's number: the open questions of each zone's default bucket, Knowledge's included
    menu, per_group = {}, {}
    for info in zone_info:
        key = "%s|%s" % (info["zone"], info["default"])
        if key in buckets:
            menu[info["zone"]] = len(buckets[key]["questions"]) + len(knowledge)
        # each group's own open count, for the menu to name apart (#384): never added up, and Knowledge apart
        per_group[info["zone"]] = [{"h": v["heading"], "n": len(buckets[v["key"]]["questions"])}
                                   for v in group_views([info]) if v["kind"] != "unattributed"]
    return {"today": today.isoformat(), "root": str(ws), "zones": zone_info, "select": selections(zone_info), "buckets": buckets, "knowledge": knowledge,
            "knowledge_answered": answered_k, "menu": menu, "menu_groups": per_group,
            "menu_knowledge": len(knowledge)}


def counts_of(data: dict) -> dict:
    """The panel's menu rows. "g" is each zone's groups with the open count of
    each, "k" the open Knowledge questions, which carry no party: the app names
    them apart and adds none of them (#384). "z" is the count of each zone's
    default group with Knowledge, as 0.56.0 sent it, for a menu not yet updated;
    it is not added up either."""
    return {"z": dict(data.get("menu") or {}), "g": dict(data.get("menu_groups") or {}), "k": int(data.get("menu_knowledge") or 0)}


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
            '<div class="qp-show"><span>Show</span><div class="qp-switch" id="qp-source" role="group" aria-label="Show">'
            '<button type="button" data-source="wiki" aria-pressed="true">Wiki questions</button>'
            '<button type="button" data-source="nurture" aria-pressed="false">Nurture findings</button></div></div>'
            '<label class="qp-wikiq-only">Wiki <select id="qp-wiki"><option value="">Both</option>'
            '<option value="Meetings">Meetings</option><option value="Knowledge">Knowledge</option></select></label>'
            '<label id="qp-party-l">Party <select id="qp-party"></select></label>'
            '<label class="qp-wikiq-only">Age <select id="qp-age"><option value="any">Any</option>'
            '<option value="week">A week or more</option><option value="month">A month or more</option></select></label>'
            '</div>'
            '<div id="qp-wikiq"><div class="qp-cols"><ol class="qp-list" id="qp-list"></ol><div class="qp-open" id="qp-open"></div></div>'
            '<div id="qp-verdicts"></div><div id="qp-decisions"></div>'
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
.qp-show{display:flex;align-items:center;gap:6px;color:var(--ink2)}
.qp-switch{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.qp-switch button{font:inherit;font-size:13px;color:var(--ink2);background:var(--surface);border:0;padding:4px 12px;cursor:pointer}
.qp-switch button+button{border-left:1px solid var(--line)}
.qp-switch button[aria-pressed=true]{color:var(--ink);background:var(--raise);box-shadow:inset 0 -2px 0 var(--accent)}
.qp-list li.qp-gh{cursor:default;font-weight:600;background:var(--bg);color:var(--ink2)}
.qp-gcount{display:flex;flex-wrap:wrap;gap:8px;align-items:center;width:100%}.qp-gcount strong{font-size:13px}
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
var zones=D.zones||[];if(S.zone!=='*'&&!zones.some(function(z){return z.zone===S.zone}))S.zone=zones.length?zones[0].zone:'';
function zinfo(){return zones.filter(function(z){return z.zone===S.zone})[0]||{scopes:[]}}
function scopes(){if(S.zone!=='*')return zinfo().scopes;var o=[];zones.forEach(function(z){z.scopes.forEach(function(s){o.push(s)})});return o}
function scoped(){return scopes().length>0}
/* the party shown: * is All; a zone shown alone with a party that is not its own reads as its default */
function pkey(){var l=scopes();if(!l.length)return S.zone==='*'?'*':'';if(S.party==='*')return'*';
if(l.some(function(s){return s.tag===S.party}))return S.party;return S.zone==='*'?'*':zinfo().default}
/* the groups to show come from the page's own table (group_views in Python), never worked out here */
function sel(){return(D.select||{})[S.zone+'|'+pkey()]||{views:[],sum:false}}
var EMPTY={questions:[],answered:0,decisions:[],review:{entities:[],people:[],read:[]},picks:{entities:[],parties:[]}};
function bucketOf(k){return(D.buckets||{})[k]||EMPTY}
function qviews(){return sel().views.filter(function(v){return v.kind!=='unattributed'})}
function uviews(){return sel().views.filter(function(v){return v.kind==='unattributed'})}
function key(q){return q.wiki+'/'+q.file}
function age(q){return Math.floor((new Date(D.today)-new Date(q.asked||D.today))/864e5)}
var AGE={any:0,week:7,month:30};
/* one entry per group: its own questions and its own count. Knowledge carries no party, so it is a group of its own. */
function groups(){var gs=qviews().map(function(v){var b=bucketOf(v.key);return{v:v,qs:b.questions.filter(function(q){return !S.gone[key(q)]}),answered:b.answered,decs:b.decisions||[]}});
var k=(D.knowledge||[]).filter(function(q){return !S.gone[key(q)]});
if(k.length||D.knowledge_answered)gs.push({v:{key:'knowledge',heading:'Knowledge',kind:'knowledge'},qs:k,answered:D.knowledge_answered||0});return gs}
function shown(){var flat=[],gs=groups();gs.forEach(function(g){g.items=g.qs.filter(function(q){return !q.verdict&&(!S.wiki||q.wiki===S.wiki)&&age(q)>=AGE[S.age]})
.sort(function(a,b){return(a.asked||'').localeCompare(b.asked||'')||a.file.localeCompare(b.file)});g.items.forEach(function(q){flat.push({q:q,g:g})})});return{gs:gs,flat:flat}}
function ekey(e){return e.g.v.key+'|'+key(e.q)}
function open(qs){return qs.filter(function(q){return !q.verdict}).length}
/* A number stands for several groups only where the table says one may (sum): otherwise each group counts alone. */
function wikiN(){if(!sel().sum)return null;var n=0;groups().forEach(function(g){n+=open(g.qs)});return n}
function nurtureN(){if(!sel().sum)return null;var n=0;
uviews().forEach(function(v){n+=bucketOf(v.key).review.entities.filter(function(r){return !S.gone['r:'+r.key]}).length});
qviews().forEach(function(v){n+=bucketOf(v.key).review.people.filter(function(r){return !S.gone['r:'+r.key]}).length});return n}
function counts(){var c=$('qp-counts'),gs=groups();c.textContent='';
function chips(box,qs,ans,decs){function chip(n,t){var s=el('span','chip');s.appendChild(el('b','',String(n)));s.appendChild(document.createTextNode(t));box.appendChild(s)}
chip(open(qs),'open');chip(qs.filter(function(q){return q.due}).length,'due today');chip(qs.filter(function(q){return q.verdict}).length,'proposed verdicts');chip(decs,'decisions to review');chip(ans,'answered, not worked in')}
if(sel().sum){var all=[],ans=0,dn=0;gs.forEach(function(g){all=all.concat(g.qs);ans+=g.answered;dn+=g.decs.length});chips(c,all,ans,dn)}
else gs.forEach(function(g){var row=el('div','qp-gcount');row.appendChild(el('strong','',g.v.heading));chips(row,g.qs,g.answered,g.decs.length);c.appendChild(row)});
var tn=$('qp-tab-n');if(tn){var n=wikiN();tn.textContent=n===null?'':String(n)}}
function answeredText(){var gs=groups().filter(function(g){return g.answered});if(sel().sum)return gs.reduce(function(n,g){return n+g.answered},0)+' answered, waiting to be worked in.';
return gs.map(function(g){return g.v.heading+' '+g.answered}).join('; ')+' answered, waiting to be worked in.'}
function fill(sel,opts,cur){sel.textContent='';opts.forEach(function(o){var e=el('option','',o[1]);e.value=o[0];if(o[0]===cur)e.selected=true;sel.appendChild(e)})}
function bar(){fill($('qp-zone'),[['*','All']].concat(zones.map(function(z){return[z.zone,z.zone]})),S.zone);
var sc=scopes();$('qp-party-l').hidden=!sc.length;if(sc.length)fill($('qp-party'),[['*','All']].concat(sc.map(function(s){return[s.tag,s.name]})),pkey());
$('qp-wiki').value=S.wiki;$('qp-age').value=S.age;
[['wiki','Wiki questions',wikiN()],['nurture','Nurture findings',nurtureN()]].forEach(function(o){var b=root.querySelector('#qp-source [data-source="'+o[0]+'"]');
b.textContent=o[1]+(o[2]===null?'':' '+o[2]);b.setAttribute('aria-pressed',S.source===o[0]?'true':'false')});
root.querySelectorAll('.qp-wikiq-only').forEach(function(e){e.hidden=S.source!=='wiki'});
$('qp-wikiq').hidden=S.source!=='wiki';$('qp-nurture').hidden=S.source!=='nurture'}
/* ---- one question open at a time ---- */
function act(q,said){if(!host){say('Answer this in the Garrick app: a browser cannot change anything.');return false}
host.postMessage({act:q});say(said);return true}
function phrase(q,how,extra){var w=(q.wiki==='Knowledge'?'the Knowledge':'the Meetings')+' question';
return how==='decide'?'record '+w+' “'+q.title+'” as a decision, in these words: '+extra:how==='answer'?'answer '+w+' “'+q.title+'” with: '+extra:how==='later'?'put off '+w+' “'+q.title+'” until '+extra:'close '+w+' “'+q.title+'”'}
function copyWords(q,how,extra){var p=phrase(q,how,extra);if(window.GarrickCopy)GarrickCopy(p).then(function(){say('Copied. Paste it to your assistant.')})}
function list(){var v=shown(),ol=$('qp-list'),es=v.flat;ol.textContent='';
var many=v.gs.length>1;
if(!es.length&&!many){ol.appendChild(el('li','qp-empty','Nothing open here.'));$('qp-open').textContent='';return}
var at=es.findIndex(function(e){return ekey(e)===S.cursor});if(at<0){at=0;S.cursor=es.length?ekey(es[0]):''}
v.gs.forEach(function(g){if(many){var h=el('li','qp-gh',g.v.heading+' ('+open(g.qs)+')');h.setAttribute('role','presentation');ol.appendChild(h)}
g.items.forEach(function(q){var e=es.filter(function(x){return x.q===q&&x.g===g})[0],i=es.indexOf(e);
var li=el('li',i===at?'on':'',q.title);li.appendChild(el('small','',q.wiki+(q.asked?' · asked '+q.asked:'')+(q.due?' · due':'')));
li.onclick=function(){S.cursor=ekey(e);keep();list()};ol.appendChild(li)})});
if(!es.length){ol.appendChild(el('li','qp-empty','Nothing open here.'));$('qp-open').textContent='';return}
opened(es[at].q,es[at+1]||es[at-1]||null)}
function opened(q,nextE){var box=$('qp-open');box.textContent='';box.appendChild(el('h3','',q.title));
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
function req(how,extra){var r={verb:'question-'+how,wiki:q.wiki,file:q.file};if(how==='answer'||how==='decide')r.words=extra;if(how==='later')r.until=extra;return r}
function go(how,extra,said){if(!host){copyWords(q,how,extra);return}
if(act(req(how,extra),said)){S.gone[key(q)]=1;S.cursor=nextE?ekey(nextE):'';delete S.typed[key(q)];keep();counts();list()}}
function save(){var v=ta.value.trim();if(!v){ta.focus();return}go('answer',v,'Filing your answer…')}
ans.onclick=save;ta.onkeydown=function(e){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();save()}};
lat.onclick=function(){if(!date.value){date.focus();say('Pick the day to come back on.');return}go('later',date.value,'Putting it off…')};
clo.onclick=function(){go('close','','Closing…')};
dec.onclick=function(){var v=ta.value.trim();if(!v){ta.focus();say('Say the decision in your own words first.');return}go('decide',v,'Recording the decision…')};
if(!q.writes.decide){dec.disabled=true;dec.title='A Knowledge question has no zone and no parties for a decision to carry'}
else{dec.title='Files your words as the raw answer and as a decision that stands as valid';dec.addEventListener('mouseover',function(){writes('decide')})}
[ans,date,lat,clo,dec].forEach(function(b){acts.appendChild(b)});box.appendChild(acts);
lat.addEventListener('mouseover',function(){writes('later')});clo.addEventListener('mouseover',function(){writes('close')});ans.addEventListener('mouseover',function(){writes('answer')});
if(!host)box.appendChild(el('p','hint','In a browser this page cannot save: each button copies what to say to your assistant.'))}
/* ---- proposed verdicts, one by one or all at once, each a close ---- */
var line=[];
function drain(){var q=line.shift();if(!q)return;if(S.gone[key(q)])return drain();S.gone[key(q)]=1;keep();act({verb:'question-close',wiki:q.wiki,file:q.file},'Closing…')}
function vlist(){var box=$('qp-verdicts'),gs=groups().filter(function(g){return g.qs.some(function(q){return q.verdict})});box.textContent='';
gs.forEach(function(g){var vs=g.qs.filter(function(q){return q.verdict});
var h=el('div','qp-group');h.appendChild(el('h3','',groups().length>1?'Proposed verdicts · '+g.v.heading:'Proposed verdicts'));
vs.forEach(function(q){var r=el('div','qp-row');r.appendChild(el('div','',q.title));r.appendChild(el('div','',q.verdict+(q.reason?': '+q.reason:'')));
var b=el('button','act','Accept');b.type='button';b.onclick=function(){if(!host){copyWords(q,'close');return}line=[q];drain();all()};
r.appendChild(b);h.appendChild(r)});
/* Accept all closes the group's own, one question at a time, each as a save from its own view */
var every=el('button','act primary','Accept all');every.type='button';every.onclick=function(){if(!host){say('Accept them one at a time in a browser.');return}line=vs.slice();drain();all()};
h.appendChild(every);box.appendChild(h)})}
/* ---- decisions the assistant flagged for a second look, per group: opened in the note app, settled by hand ---- */
function dlist(){var box=$('qp-decisions'),gs=groups().filter(function(g){return g.decs.length});box.textContent='';
gs.forEach(function(g){var h=el('div','qp-group');h.appendChild(el('h3','',groups().length>1?'Decisions to review · '+g.v.heading:'Decisions to review'));
g.decs.forEach(function(d){var r=el('div','qp-row');r.appendChild(d.href?link(d.title,d.href):el('span','',d.title));
r.appendChild(el('div','',(d.decided?'Decided '+d.decided+'. ':'')+'Revisit: '+d.revisit));h.appendChild(r)});box.appendChild(h)})}
/* ---- Work them in: the route Process the Inbox takes ---- */
function work(){var box=$('qp-work');box.textContent='';if(!groups().some(function(g){return g.answered}))return;
var b=el('button','act primary','Work them in');b.type='button';b.setAttribute('data-request','work through the open questions');
b.setAttribute('data-folder',D.root||'');b.title='Hand “work through the open questions” to your assistant';box.appendChild(b);
box.appendChild(el('span','hint',answeredText()))}
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
var ed=el('label'),edc=mk('input','checkbox','', 'edit',false);ed.appendChild(edc);ed.appendChild(document.createTextNode('Edit'));if(kind==='organisation')ch.appendChild(ed);row.appendChild(ch);
var extra=el('div','qp-extra');row.appendChild(extra);
var pick=el('input');pick.type='text';pick.setAttribute('aria-label','Another page');pick.autocomplete='off';pick.placeholder=kind==='organisation'?'An entity page':'A party, or none';
var dl=el('datalist');dl.id='dl-'+r.key;pick.setAttribute('list',dl.id);
((kind==='organisation'?(bk.picks.entities||[]).map(function(e){return[e.rel,e.title+(e.aliases.length?' ('+e.aliases.join(', ')+')':'')]}):(bk.picks.parties||[]).map(function(p){return[p.tag,p.name]}))).forEach(function(o){var op=el('option');op.value=o[0];op.label=o[1];dl.appendChild(op)});
var oldv=mk('input','text','','',false),newv=mk('input','text','','',false),until=mk('input','date','','',false);
oldv.setAttribute('aria-label','The value as written');oldv.placeholder='The value as written (three characters or more)';newv.setAttribute('aria-label','What it should be');newv.placeholder='What it should be';until.setAttribute('aria-label','Come back on');
[pick,dl,oldv,newv,until].forEach(function(e){extra.appendChild(e)});
function choice(){var c=ch.querySelector('input[type=radio]:checked');return c?c.value:'none'}
function paint(){var c=choice();pick.hidden=c!=='another';until.hidden=c!=='later';oldv.hidden=newv.hidden=!edc.checked;extra.hidden=pick.hidden&&until.hidden&&oldv.hidden;if(out.change)out.change()}
ch.addEventListener('change',paint);
var out={key:r.key,el:row,
action:function(){var c=choice(),e=edc.checked&&oldv.value&&newv.value;if(c==='yes'||c==='another')return'save';if(c==='later')return'later';
if(c==='no')return'no';return e?'save':'none'},
value:function(){var c=choice(),v={do:kind,key:r.key,path:r.path};
if(c==='yes'||c==='another'||c==='later'||c==='no'){v.choice=c;if(c==='another')v.pick=pick.value.trim();if(c==='later')v.until=until.value}
else{v.do='correct';v.choice='yes'}
if(edc.checked&&oldv.value&&newv.value)v.edit={old:oldv.value,new:newv.value};return v}};
paint();return out}
function review(){var box=$('qp-nurture');box.textContent='';rows=[];var secs=[],zs=[],labels=[];
sel().views.forEach(function(v){if(zs.indexOf(v.zone)<0)zs.push(v.zone)});
zs.forEach(function(z){var vs=sel().views.filter(function(v){return v.zone===z});
vs.filter(function(v){return v.kind==='unattributed'}).concat(vs.filter(function(v){return v.kind!=='unattributed'})).forEach(function(v){
var b=bucketOf(v.key),un=v.kind==='unattributed',items=(un?b.review.entities:b.review.people).filter(function(r){return !S.gone['r:'+r.key]});
secs.push({v:v,b:b,un:un,items:items,rows:[]})})});
var many=sel().views.length>1&&!sel().sum;
function nOf(rs){return rs.filter(function(r){return r.action()==='save'}).length}
function label(btn,rs){btn.textContent='Save '+nOf(rs)+' answer'+(nOf(rs)===1?'':'s')}
/* A save is one request per group, however many groups are on the screen: the page sends each group with the view its rows were shown in. */
function groupOf(sec){var rs=sec.rows.filter(function(r){return r.action()!=='none'}),g={zone:sec.un?'unattributed':sec.v.zone,rows:rs.map(function(r){return r.value()})};
var sc=sec.un?sec.v.zone:sec.v.party;if(sc)g.scope=sc;return g}
function send(list){var gs=list.map(groupOf).filter(function(g){return g.rows.length});if(!gs.length){say('Nothing to save.');return}
if(gs.length===1)act({verb:'nurture-save',zone:gs[0].zone,scope:gs[0].scope,rows:gs[0].rows},'Saving…');
else act({verb:'nurture-save-all',groups:gs},'Saving…')}
secs.forEach(function(sec){if(!sec.items.length)return;
var d=el('div','qp-group');d.appendChild(el('h3','',sec.v.heading+': '+(sec.un?'whose entity pages are':'where people work')+', '+sec.items.length));
sec.items.forEach(function(r){var row=rowFor(r,sec.b,sec.un?'answer':'organisation');sec.rows.push(row);rows.push(row);d.appendChild(row.el)});
if(many){var sb=el('button','act primary qp-hostonly');sb.type='button';sec.rows.forEach(function(r){r.change=function(){labels.forEach(function(f){f()})}});
var f=function(){label(sb,sec.rows)};labels.push(f);f();sb.onclick=function(){send([sec])};var ft=el('div','qp-save');ft.appendChild(sb);d.appendChild(ft)}
box.appendChild(d)});
qviews().forEach(function(v){var rd=bucketOf(v.key).review.read;if(!rd.length)return;
var d=el('details','qp-group');d.appendChild(el('summary','',(sel().views.length>1?v.heading+': ':'')+'Judgment and other findings, to open ('+rd.length+')'));
rd.forEach(function(r){var p=el('div','qp-row');p.appendChild(link(r.path,r.href));p.appendChild(el('div','',r.check));p.appendChild(el('div'));d.appendChild(p)});box.appendChild(d)});
if(!rows.length){box.appendChild(el('div','qp-empty','No findings to answer here.'));return}
var foot=el('div','qp-save'),sv=el('button','act primary qp-hostonly');sv.type='button';
if(many){sv.textContent='Save all answers'}
else{rows.forEach(function(r){r.change=function(){label(sv,rows)}});label(sv,rows)}
sv.onclick=function(){send(secs)};
foot.appendChild(sv);
var web=el('button','act qp-webonly','Review in the chat');web.type='button';web.setAttribute('data-request','review the context with me');web.setAttribute('data-folder',D.root||'');
foot.appendChild(web);box.appendChild(foot)}
var prevActed=window.GarrickActed;window.GarrickActed=function(q,res){
if(q&&(q.verb==='nurture-save'||q.verb==='nurture-save-all')){(res&&res.rows||[]).forEach(function(x){var r=rows.filter(function(y){return y.key===x.key})[0];if(!r)return;
if(x.ok){S.gone['r:'+x.key]=1}else{r.el.classList.add('refused');var m=r.el.querySelector('.qp-say');if(!m){m=el('div','qp-say');r.el.appendChild(m)}m.textContent=x.say}});
keep();if(res&&res.ok){var m=rows.filter(function(r){return r.el.classList.contains('refused')});if(!m.length)setTimeout(review,0)}}
if(q&&q.verb==='question-close'&&line.length)drain();
if(prevActed)return prevActed(q,res)};
function all(){bar();counts();list();vlist();dlist();work();review();keep()}
$('qp-zone').onchange=function(){S.zone=this.value;S.party=this.value==='*'?'*':'';S.cursor='';all()};
$('qp-party').onchange=function(){S.party=this.value;S.cursor='';all()};
root.querySelectorAll('#qp-source button').forEach(function(b){b.onclick=function(){S.source=b.getAttribute('data-source');all()}});
$('qp-wiki').onchange=function(){S.wiki=this.value;S.cursor='';all()};
$('qp-age').onchange=function(){S.age=this.value;S.cursor='';all()};
window.GarrickQuestions={open:function(){if(window.StatusTab)StatusTab('questions');window.scrollTo(0,0);var t=root.querySelector('textarea');if(t)t.focus()}};
all()})();
"""
