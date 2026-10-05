#!/usr/bin/env python3
"""Mechanical steps for the intake skill: what is waiting, what it says, and
moving it to the place the skill chose.

Everything that comes in lands in an inbox first: a transcript in
`Wikis/Meetings/raw/inbox/`, and mail or any other file in a zone's `Inbox/`.
Whatever put it there (you, a mail rule, a script, your assistant's own
connector) decided nothing. Where it goes is decided by the rules, in
`System/rules.md`, and by whoever runs the skill. This script never decides it:
it lists, parses, suggests parties from mail domains as a hint, and files an
item only into the destination it is given, after checking the zone and the
wall.

    python3 intake.py list [--json]                         everything waiting, in every inbox
    python3 intake.py parse --file FILE                     one item as JSON: headers, text, attachments, suggested parties
    python3 intake.py file-conversation --file FILE --parties a,b [--title "..."] [--date YYYY-MM-DD]
    python3 intake.py file-reading --file FILE [--title "..."] [--slug SLUG]
    python3 intake.py file-to-project --file FILE --project PATH --parties a,b [--name NAME]
    python3 intake.py extract-attachment --mail RAW --project PATH (--name NAME | --index N) [--save-as NAME]
    python3 intake.py learn --domain DOMAIN --party TAG     mail from DOMAIN suggests TAG from now on

Every command takes `--root PATH` (default: the workspace this script sits in)
and `--today YYYY-MM-DD`. Standard library only, Python 3.9 or later. On
refusal, one line to stderr and exit 1.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # keep this skill folder free of __pycache__

import argparse  # noqa: E402
import datetime  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional, Tuple  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
sys.path.insert(0, str(HERE.parent / "meetings"))

from garrick_lib import (  # noqa: E402
    INBOX,
    MEDIA_EXTS,
    is_domain,
    is_webmail,
    load_context,
    mail_attachments,
    parse_frontmatter,
    parse_mail,
    strip_recipients,
    parties_for_domain,
    split_domains,
    strip_tag,
    walled,
    workspace_root,
)
from ingest import RAW_EXTS, Refusal, _stems, build_slug, meetings_root, no_links  # noqa: E402

BODY_LIMIT = 50_000  # characters of text `parse` gives; the file keeps the rest
TEXT_EXTS = {".md", ".txt", ".csv", ".tsv", ".json", ".html", ".htm", ".vtt", ".xml", ".yaml", ".yml"}
SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:re|fw|fwd|aw|wg|sv|vs|tr|rif|r)\s*(?:\[\d+\])?\s*:\s*", re.I)
KINDS = ("transcript", "mail", "file", "unreadable")
WALL_REFUSAL = ("Refused: a wall stands between that project's party and the parties this came from. "
                "Nothing was moved. Tell the user only that a wall held something back.")


# --------------------------------------------------------------------------- where


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def place_of(root: Path, path: Path) -> Tuple[str, str]:
    """("meetings", "") for the Meetings inbox, ("zone", <Zone>) for a zone's
    Inbox. Refuses a file anywhere else: only an inbox is waiting to be filed."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        parts = ()
    if len(parts) == 4 and parts[0] == "Zones" and parts[2] == INBOX and not parts[1].startswith((".", "_")):
        return "zone", parts[1]
    if len(parts) == 5 and parts[:4] == ("Wikis", "Meetings", "raw", "inbox"):
        return "meetings", ""
    raise Refusal("%s is not in an inbox: Zones/<Zone>/%s/ or Wikis/Meetings/raw/inbox/." % (path.name, INBOX))


def _parse_quietly(path: Path) -> Optional[dict]:
    try:
        return parse_mail(path)
    except Exception:  # an unreadable file is still listed, as a file
        return None


def kind_of(path: Path, where: str) -> Tuple[str, Optional[dict]]:
    """What an inbox item is, by its form alone, and its parsed headers when it
    is mail. `transcript`, `mail`, `file` or `unreadable`. The form says nothing
    about where the item goes."""
    ext = path.suffix.lower()
    if ext in MEDIA_EXTS:
        return "unreadable", None
    if where == "meetings":
        return ("transcript" if ext in RAW_EXTS else "unreadable"), None
    if ext == ".vtt":
        return "transcript", None
    if ext == ".eml":
        return "mail", _parse_quietly(path)
    if ext in (".md", ".txt"):
        m = _parse_quietly(path)
        if m and m["from"]:
            return "mail", m
    return "file", None


def _waiting(folder: Path) -> List[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


def _zones(root: Path) -> List[Path]:
    zones = root / "Zones"
    if not zones.is_dir():
        return []
    return sorted(z for z in zones.iterdir() if z.is_dir() and not z.name.startswith((".", "_")))


def _fmt(pairs) -> List[str]:
    return ["%s <%s>" % (n, a) if n else a for n, a in pairs]


def list_items(root: Path) -> List[dict]:
    """Every item waiting, in every inbox: the Meetings inbox first, then each
    zone's, mail and files together, oldest first by the date they were sent
    (files, which carry none, after the mail). A file that cannot be read is
    listed as `unreadable`, so it is mentioned rather than skipped."""
    out: List[dict] = []
    for p in _waiting(meetings_root(root) / "raw" / "inbox"):
        kind, _ = kind_of(p, "meetings")
        out.append({"kind": kind, "zone": "", "file": _rel(root, p), "date": "", "from": "", "subject": ""})
    rest = []
    for zone in _zones(root):
        for p in _waiting(zone / INBOX):
            kind, m = kind_of(p, "zone")
            item = {"kind": kind, "zone": zone.name, "file": _rel(root, p), "date": "", "from": "", "subject": ""}
            sent = ""
            if m:
                item.update({"date": m["date"] or "", "from": ", ".join(_fmt(m["from"])), "subject": m["subject"]})
                sent = m["sent"] or ""
            rest.append((sent or "9999", zone.name, p.name, item))
    out += [item for *_, item in sorted(rest, key=lambda r: r[:3])]
    return out


# --------------------------------------------------------------------------- suggested parties


def _name(ctx: dict, tag: str) -> str:
    entry = ctx["parties"].get(tag) or {}
    return entry.get("party") or tag


def suggest(ctx: dict, zone: str, mail: dict) -> dict:
    """Which parties a mail's addresses point to, and when to ask. A hint only.

    Domains are matched against the Domains column of Parties. A plus tag
    (`you+acme@...`) that is a party's tag is a strong hint, on any domain.
    Personal webmail never names a party by itself. The hint says to ask when
    nothing matches, when a domain belongs to two parties, when two parties on
    the mail are walled from each other, or when a party belongs to another
    zone. It never picks one side of a wall, and never says where the mail goes.
    """
    addresses = []
    for key in ("from", "to", "cc", "delivered", "forwarded"):
        addresses += [addr for _, addr in mail.get(key, [])]
    plus, webmail, unknown = [], [], []
    by_domain: Dict[str, List[str]] = {}
    for addr in addresses:
        local, _, domain = addr.rpartition("@")
        if "+" in local:
            tag = strip_tag(local.split("+", 1)[1])
            if tag in ctx["parties"] and tag not in plus:
                plus.append(tag)
        if is_webmail(domain):
            if domain not in webmail:
                webmail.append(domain)
            continue
        tags = parties_for_domain(ctx, domain)
        if tags:
            by_domain[domain] = tags
        elif domain and domain not in unknown:
            unknown.append(domain)

    ask: List[str] = []
    parties = set(plus)
    for domain, tags in sorted(by_domain.items()):
        if len(tags) > 1:
            ask.append("%s is listed for %s." % (domain, " and ".join(_name(ctx, t) for t in tags)))
        else:
            parties.add(tags[0])
    parties_list = sorted(parties)
    if not parties_list and not any(len(t) > 1 for t in by_domain.values()):
        if webmail and not unknown:
            ask.append("It is from personal webmail (%s), which never names a party." % ", ".join(webmail))
        elif unknown:
            ask.append("No party has the domain %s." % ", ".join(unknown))
        else:
            ask.append("There is no address on it to go by.")
    for i, a in enumerate(parties_list):
        for b in parties_list[i + 1:]:
            if walled(ctx, a, b):
                ask.append("%s and %s are both on it, and a wall stands between them." % (_name(ctx, a), _name(ctx, b)))
    for tag in parties_list:
        pzone = (ctx["parties"][tag].get("zone") or "").strip()
        if zone and pzone and pzone != zone:
            ask.append("%s is a %s party, but this mail is in the %s inbox." % (_name(ctx, tag), pzone, zone))
    sender_domains = [addr.rpartition("@")[2] for _, addr in mail.get("from", [])]
    return {"parties": parties_list, "ask": ask, "plus": sorted(plus), "domains": by_domain,
            "unknown": unknown, "webmail": webmail,
            "sender_webmail": bool(sender_domains) and all(is_webmail(d) for d in sender_domains)}


# --------------------------------------------------------------------------- parse


def title_from_subject(subject: str) -> str:
    title = subject or ""
    while True:
        stripped = SUBJECT_PREFIX_RE.sub("", title, count=1)
        if stripped == title:
            break
        title = stripped
    return title.strip()


def _item(root: Path, path: Path) -> Tuple[Path, str, str, str, Optional[dict]]:
    """(path, where, zone, kind, parsed mail) for a file waiting in an inbox."""
    path = Path(path)
    if not path.is_file():
        raise Refusal("%s is not a file." % path)
    if path.is_symlink():
        raise Refusal("%s is a symbolic link. Drop the file itself into the inbox; Garrick never files a link."
                      % path.name)
    where, zone = place_of(root, path)
    kind, m = kind_of(path, where)
    return path, where, zone, kind, m


def _text_of(path: Path) -> Optional[str]:
    if path.suffix.lower() not in TEXT_EXTS:
        return None
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def parse(root: Path, path: Path) -> dict:
    """Everything the skill needs to decide what an item is and where it goes.
    Says nothing about where it goes."""
    path, where, zone, kind, m = _item(root, path)
    info = {"file": _rel(root, path), "zone": zone, "kind": kind, "name": path.name,
            "bytes": path.stat().st_size}
    if kind != "mail":
        text = _text_of(path) if kind != "unreadable" else None
        info.update({"text": (text or "")[:BODY_LIMIT] if text is not None else None,
                     "truncated": text is not None and len(text) > BODY_LIMIT})
        return info
    m = m or parse_mail(path)
    date, date_from = m["date"], "header"
    if not date:
        date = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
        date_from = "file time"
    body = m["body"]
    info.update({
        "date": date,
        "date_from": date_from,
        "subject": m["subject"],
        "title": title_from_subject(m["subject"]),
        "from": _fmt(m["from"]),
        "to": _fmt(m["to"]),
        "cc": _fmt(m["cc"]),
        "mailing_list": m.get("mailing_list", False),
        "attachments": m["attachments"],
        "suggested": suggest(load_context(root), zone, m),
        "text": body[:BODY_LIMIT],
        "truncated": len(body) > BODY_LIMIT,
    })
    return info


# --------------------------------------------------------------------------- file a conversation


def _yaml(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def _block(key: str, values: List[str]) -> List[str]:
    if not values:
        return ["%s: []" % key]
    return ["%s:" % key] + ["  - %s" % _yaml(v) for v in values]


def _names(pairs) -> str:
    return ", ".join(n or a for n, a in pairs)


def draft_page(title: str, date: str, zone: str, parties: List[str], slug: str, mail: dict, today: str) -> str:
    when = datetime.date.fromisoformat(date)
    sender = _names(mail["from"]) or "an unknown sender"
    lines = ["---", "title: %s" % _yaml(title), "type: email", "date: %s" % date, "zone: %s" % zone,
             "parties: [%s]" % ", ".join(parties), "from: %s" % _yaml(", ".join(_fmt(mail["from"])))]
    lines += _block("to", _fmt(mail["to"]))
    lines += _block("cc", _fmt(mail["cc"]))
    lines += ["people: []", 'raw: "[[raw/%s]]"' % slug, "created: %s" % today, "updated: %s" % today, "---", ""]
    lines += ["# %s" % title, "",
              "Mail from %s, %d %s %d." % (sender, when.day, when.strftime("%B"), when.year)
              + (" To %s." % _names(mail["to"]) if mail["to"] else "")
              + (" Copied to %s." % _names(mail["cc"]) if mail["cc"] else ""),
              "", "<What the mail says or asks, in a few sentences.>", "",
              "## Wording that matters", "",
              "<Quotes where the exact words are the point: a commitment, a number, a refusal. Else delete this section.>", "",
              "## Actions", "", "| What | Who | By when |", "|---|---|---|", ""]
    if mail["attachments"]:
        lines += ["## Attachments", "", "Kept inside the raw record.", ""]
        lines += ["- %s (%s, %d bytes)" % (a["name"], a["type"], a["bytes"]) for a in mail["attachments"]]
        lines.append("")
    return "\n".join(lines)


def _known_tags(ctx: dict, parties: List[str], what: str) -> List[str]:
    tags = sorted(dict.fromkeys(strip_tag(t) for t in parties if strip_tag(t)))
    if not tags:
        raise Refusal("%s needs its parties; ask whose it is." % what)
    unknown = [t for t in tags if t not in ctx["parties"]]
    if unknown:
        raise Refusal("%s is not a party tag in System/context.md; add the party first." % ", ".join(unknown))
    return tags


def file_conversation(root: Path, path: Path, parties: List[str], title: str = "", date: str = "",
                      today: Optional[str] = None) -> Tuple[str, Path, Path]:
    """Record a mail from a zone's Inbox as a conversation: move the original,
    untouched, into `Wikis/Meetings/raw/` and write its draft page beside the
    meeting pages, with the zone it was dropped in and the parties given.

    Refuses anything but mail in a zone Inbox, no parties or an unknown one,
    and a mail with no date or title to go by. Never overwrites. Returns
    (slug, raw path, page path).
    """
    path, where, zone, kind, m = _item(root, path)
    if where != "zone":
        raise Refusal("%s is in the Meetings inbox; a transcript is landed with the meetings skill's ingest.py land."
                      % path.name)
    if kind != "mail":
        raise Refusal("%s is not a mail. A transcript or call notes are landed with ingest.py land; "
                      "anything else goes to Knowledge or a project." % path.name)
    ctx = load_context(root)
    tags = _known_tags(ctx, parties, "A mail")
    mail = m or parse_mail(path)
    date = date or mail["date"] or ""
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        raise Refusal("This mail has no date to go by; pass --date YYYY-MM-DD." if not date
                      else '"%s" is not a date (YYYY-MM-DD).' % date)
    title = (title or title_from_subject(mail["subject"])).strip()
    if not title:
        raise Refusal("This mail has no subject; pass --title with a few words for what it is about.")
    raw_dir = meetings_root(root) / "raw"
    sources = meetings_root(root) / "wiki" / "sources"
    if not raw_dir.is_dir():
        raise Refusal("%s does not exist; is %s an installed workspace?" % (raw_dir, root))
    slug = build_slug(date, title, _stems(raw_dir, sources))
    dest = raw_dir / (slug + path.suffix.lower())
    page = sources / (slug + ".md")
    no_links(root, dest, page)
    sources.mkdir(parents=True, exist_ok=True)
    today = today or datetime.date.today().isoformat()
    text = draft_page(title, date, zone, tags, slug, mail, today)
    shutil.move(str(path), str(dest))
    page.write_text(text, encoding="utf-8")
    return slug, dest, page


# --------------------------------------------------------------------------- file something to read


def reading_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def file_reading(root: Path, path: Path, title: str = "", slug: str = "",
                 today: Optional[str] = None) -> Tuple[str, Path, Path]:
    """Freeze an item from a zone's Inbox into `Wikis/Knowledge/raw/` and write a
    draft source page for the knowledge skill to finish. A mail is frozen with
    the reader's own addresses removed (`strip_recipients`); anything else is
    moved untouched.

    The page carries no zone and no parties: Knowledge holds published
    material, usable anywhere. Refuses audio, a transcript, and a slug already
    used; never overwrites. Returns (slug, raw path, page path).
    """
    path, where, zone, kind, m = _item(root, path)
    if where != "zone":
        raise Refusal("%s is in the Meetings inbox, which holds conversations, never reading." % path.name)
    if kind in ("unreadable", "transcript"):
        raise Refusal("%s is %s, which is never filed as reading." % (
            path.name, "a transcript, a conversation," if kind == "transcript" else "audio or video"))
    mail = m if kind == "mail" else None
    title = (title or (title_from_subject(mail["subject"]) if mail else "") or path.stem).strip()
    slug = reading_slug(slug or title)
    if not slug:
        raise Refusal("Pass --title or --slug: there is nothing to name this by.")
    kroot = root / "Wikis" / "Knowledge"
    raw_dir, sources = kroot / "raw", kroot / "wiki" / "sources"
    if not raw_dir.is_dir():
        raise Refusal("%s does not exist; is %s an installed workspace?" % (raw_dir, root))
    if slug in _stems(raw_dir, sources):
        raise Refusal("%s is already used in Knowledge. If this is a different item, pass --slug with a "
                      "distinguishing word, not a number." % slug)
    dest = raw_dir / (slug + path.suffix.lower())
    page = sources / (slug + ".md")
    today = today or datetime.date.today().isoformat()
    if mail:
        sender = _names(mail["from"])
        author = _yaml(sender) if sender else "<who wrote or published it>"
        published = mail["date"] or "<YYYY-MM-DD, or YYYY-MM, or YYYY>"
        how = "Arrived by mail%s%s." % (" from %s" % sender if sender else "",
                                       ", %s" % mail["date"] if mail["date"] else "")
    else:
        author, published = "<who wrote or published it>", "<YYYY-MM-DD, or YYYY-MM, or YYYY>"
        how = "Dropped into the %s inbox as %s." % (zone, path.name)
    text = "\n".join([
        "---", "title: %s" % _yaml(title), "type: source", "author: %s" % author, "published: %s" % published,
        'raw: "[[raw/%s]]"' % slug, "confidence: <high, medium or low>", "created: %s" % today,
        "updated: %s" % today, "---", "", "# %s" % title, "", how, "",
        "<A short summary. Every vendor claim attributed to its vendor.>", "",
        "Touches <the concept and entity pages it speaks to>.", ""])
    no_links(root, dest, page)
    sources.mkdir(parents=True, exist_ok=True)
    if mail:
        dest.write_bytes(strip_recipients(path.read_bytes()))
        path.unlink()
    else:
        shutil.move(str(path), str(dest))
    page.write_text(text, encoding="utf-8")
    return slug, dest, page


# --------------------------------------------------------------------------- file into a project


def resolve_project(root: Path, project: Optional[str]) -> Tuple[Path, str, List[str]]:
    """(folder, zone, party tags) of the project named by an explicit path,
    `Zones/<Zone>/<Project>`. Refuses no path, and anything that is not a
    project with a hub note."""
    if not project or not str(project).strip():
        raise Refusal("Say which project: pass --project Zones/<Zone>/<Project>. Nothing is filed into a project "
                      "by default.")
    p = Path(str(project).strip()).expanduser()
    p = (p if p.is_absolute() else root / p).resolve()
    try:
        parts = p.relative_to(root.resolve()).parts
    except ValueError:
        parts = ()
    if len(parts) != 3 or parts[0] != "Zones" or parts[2] == INBOX or any(x.startswith((".", "_")) for x in parts[1:]):
        raise Refusal("%s is not a project folder, Zones/<Zone>/<Project>." % project)
    hub = parse_frontmatter(p / (p.name + ".md"))
    if hub.get("type") != "project":
        raise Refusal("%s has no project hub note, %s.md." % (_rel(root, p), p.name))
    party = hub.get("party")
    tags = [strip_tag(t) for t in (party if isinstance(party, list) else [party or ""]) if strip_tag(t)]
    if not tags:
        raise Refusal("%s has no party, so the wall cannot be checked; set its party first." % p.name)
    return p, parts[1], tags


def _check_wall(ctx: dict, project_tags: List[str], tags: List[str]) -> None:
    if any(walled(ctx, a, b) for a in project_tags for b in tags):
        raise Refusal(WALL_REFUSAL)


def _safe_name(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name.strip().lstrip(".")
    name = re.sub(r"[\x00-\x1f:]", " ", name).strip()
    if not name:
        raise Refusal("That file name is empty once unsafe characters are removed; pass a name.")
    return name


def file_to_project(root: Path, path: Path, project: Optional[str], parties: List[str], name: str = "") -> Path:
    """Move a dropped file from a zone's Inbox into the named project's `Sources/`.

    The destination is only ever the one given. Refuses without a project, a
    project in another zone, a project whose party is walled from `parties`,
    mail (a mail is recorded as a conversation first, and only its attachment
    goes to the project), audio, a name already taken, and a symbolic link
    between the workspace and the destination. Returns the new path.
    """
    path, where, zone, kind, _ = _item(root, path)
    folder, pzone, ptags = resolve_project(root, project)
    if where != "zone":
        raise Refusal("%s is in the Meetings inbox, which holds conversations, never project material." % path.name)
    if kind == "mail":
        raise Refusal("%s is a mail. File it as a conversation first (file-conversation), then save its attachment "
                      "with extract-attachment." % path.name)
    if kind == "transcript":
        raise Refusal("%s is a transcript, which is a conversation: it goes to Meetings." % path.name)
    if kind == "unreadable":
        raise Refusal("%s is audio or video, which is never filed; its transcript goes to the Meetings inbox."
                      % path.name)
    if pzone != zone:
        raise Refusal("%s is in the %s inbox but %s is in %s. Zones never mix: move the file to the %s inbox "
                      "first if that is where it belongs." % (path.name, zone, folder.name, pzone, pzone))
    ctx = load_context(root)
    tags = _known_tags(ctx, parties, "A file for a project")
    _check_wall(ctx, ptags, tags)
    dest = folder / "Sources" / _safe_name(name or path.name)
    no_links(root.resolve(), dest)
    if dest.exists():
        raise Refusal("%s already exists; pass --name for a different one." % _rel(root, dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def _filed_mail(root: Path, mail: "str | Path") -> Tuple[Path, dict]:
    raw_dir = meetings_root(root) / "raw"
    mail = str(mail)
    p = Path(mail).expanduser()
    if "/" not in mail and not p.suffix:
        p = raw_dir / (mail + ".eml")
    elif not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p.parent != raw_dir.resolve() or p.suffix.lower() != ".eml" or not p.is_file():
        raise Refusal("%s is not a filed mail. Attachments are saved from a .eml in Wikis/Meetings/raw/, once the "
                      "mail is recorded as a conversation." % mail)
    page = meetings_root(root) / "wiki" / "sources" / (p.stem + ".md")
    fm = parse_frontmatter(page)
    if not fm.get("zone") or not fm.get("parties"):
        raise Refusal("%s has no finished page with its zone and parties; file the mail as a conversation first."
                      % p.name)
    return p, fm


def extract_attachment(root: Path, mail: str, project: Optional[str], name: str = "", index: int = 0,
                       save_as: str = "") -> Tuple[str, Path]:
    """Save one attachment of a mail already recorded in Meetings into the named
    project's `Sources/`. The raw record keeps its own copy, untouched.

    Refuses a mail not yet filed as a conversation, a project in another zone
    from the mail's, a project whose party is walled from the mail's parties,
    a name already taken by a different file, and a symbolic link between the
    workspace and the destination. Returns ("saved" or "already", path).
    """
    raw, fm = _filed_mail(root, mail)
    folder, pzone, ptags = resolve_project(root, project)
    if fm.get("zone") != pzone:
        raise Refusal("That mail is in the %s zone but %s is in %s. Zones never mix." % (fm.get("zone"), folder.name, pzone))
    ctx = load_context(root)
    mparties = fm.get("parties")
    tags = [strip_tag(t) for t in (mparties if isinstance(mparties, list) else [mparties]) if strip_tag(t)]
    _check_wall(ctx, ptags, tags)
    found = mail_attachments(raw.read_bytes())
    if index:
        if not 1 <= index <= len(found):
            raise Refusal("That mail has %d attachment%s." % (len(found), "" if len(found) == 1 else "s"))
        chosen = found[index - 1]
    else:
        hits = [a for a in found if a[0] == name]
        if not name or len(hits) != 1:
            names = ", ".join(a[0] for a in found) or "none"
            raise Refusal(("Two attachments are called %s; pass --index." % name) if len(hits) > 1 else
                          "Pass --name with one of its attachments: %s." % names)
        chosen = hits[0]
    dest = folder / "Sources" / _safe_name(save_as or chosen[0])
    no_links(root.resolve(), dest)
    if dest.exists():
        if dest.read_bytes() == chosen[2]:
            return "already", dest
        raise Refusal("%s already exists and is different; pass --save-as for another name." % _rel(root, dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "xb") as f:  # never through a link put there since the check
        f.write(chosen[2])
    return "saved", dest


# --------------------------------------------------------------------------- learn


def _cells(line: str) -> List[str]:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def _row(cells: List[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def learn(root: Path, domain: str, tag: str) -> str:
    """Add `domain` to the party's Domains cell in System/context.md.

    Adds the column when the table has none. Refuses webmail, a malformed
    domain, an unknown tag, and a domain that already belongs to another
    party. Returns "added" or "already".
    """
    domain = (split_domains(domain) or [""])[0]
    if not is_domain(domain):
        raise Refusal('"%s" is not a mail domain, such as acmecorp.example.' % domain)
    if is_webmail(domain):
        raise Refusal("%s is personal webmail; anyone can have an address there, so it never names a party." % domain)
    tag = strip_tag(tag)
    path = root / "System" / "context.md"
    ctx = load_context(root)  # re-read right before writing: another session may have changed it
    if tag not in ctx["parties"]:
        raise Refusal("%s is not a party tag in System/context.md." % tag)
    if domain in ctx["parties"][tag].get("domains", []):
        return "already"
    for other, entry in ctx["parties"].items():
        if other != tag and domain in entry.get("domains", []):
            raise Refusal("%s already belongs to %s; take it off there first." % (domain, entry.get("party") or other))
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## parties"), None)
    if start is None:
        raise Refusal("System/context.md has no Parties section.")
    rows = []
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            break
        if lines[i].strip().startswith("|"):
            rows.append(i)
        elif rows:
            break
    if len(rows) < 2:
        raise Refusal("System/context.md has no Parties table.")
    header = [c.lower() for c in _cells(lines[rows[0]])]
    col = next((i for i, c in enumerate(header) if c.startswith("domain")), None)
    tag_col = next((i for i, c in enumerate(header) if c.startswith("tag")), None)
    if tag_col is None:
        raise Refusal("The Parties table in System/context.md has no Tag column.")
    if col is None:
        col = len(header)
        for n, i in enumerate(rows):
            cells = _cells(lines[i])
            cells += [""] * (col - len(cells))
            cells.append("Domains" if n == 0 else "---" if n == 1 else "")
            lines[i] = _row(cells)
    for i in rows[2:]:
        cells = _cells(lines[i])
        if len(cells) > tag_col and strip_tag(cells[tag_col]) == tag:
            cells += [""] * (col + 1 - len(cells))
            cells[col] = ", ".join(split_domains(cells[col]) + [domain])
            lines[i] = _row(cells)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "added"


# --------------------------------------------------------------------------- CLI


def _tags(value: str) -> List[str]:
    return [t for t in (value or "").split(",") if t.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="List, read and file what is waiting in the inboxes. "
                                             "Every filing command takes its destination explicitly.")
    ap.add_argument("--root", help="workspace folder (default: the one this script sits in)")
    ap.add_argument("--today", help="YYYY-MM-DD to stamp instead of today")
    sub = ap.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="every item waiting, in every inbox")
    ls.add_argument("--json", action="store_true", help="machine-readable output")
    p = sub.add_parser("parse", help="one item as JSON: headers, text, attachments, suggested parties")
    p.add_argument("--file", required=True)
    c = sub.add_parser("file-conversation", help="record a mail in Meetings: raw record and draft page")
    c.add_argument("--file", required=True)
    c.add_argument("--parties", required=True, help="comma-separated tags")
    c.add_argument("--title", default="", help="what the mail is about (default: its subject)")
    c.add_argument("--date", default="", help="YYYY-MM-DD (default: the mail's own date)")
    r = sub.add_parser("file-reading", help="freeze an item into Knowledge raw/ and write a draft source page")
    r.add_argument("--file", required=True)
    r.add_argument("--title", default="", help="title of the work (default: the subject, or the file name)")
    r.add_argument("--slug", default="", help="the name in Knowledge (default: from the title)")
    t = sub.add_parser("file-to-project", help="move a dropped file into a project's Sources/")
    t.add_argument("--file", required=True)
    t.add_argument("--project", required=True, help="Zones/<Zone>/<Project>")
    t.add_argument("--parties", required=True, help="comma-separated tags: whose material this is")
    t.add_argument("--name", default="", help="file name in Sources/ (default: as dropped)")
    x = sub.add_parser("extract-attachment", help="save a filed mail's attachment into a project's Sources/")
    x.add_argument("--mail", required=True, help="the filed mail: its slug, or Wikis/Meetings/raw/<slug>.eml")
    x.add_argument("--project", required=True, help="Zones/<Zone>/<Project>")
    x.add_argument("--name", default="", help="the attachment's name, as parse lists it")
    x.add_argument("--index", type=int, default=0, help="the attachment's place in the list, from 1")
    x.add_argument("--save-as", default="", help="file name in Sources/ (default: the attachment's)")
    l = sub.add_parser("learn", help="record that mail from a domain belongs to a party")
    l.add_argument("--domain", required=True)
    l.add_argument("--party", required=True)
    args = ap.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
    except FileNotFoundError:
        print("This script is not inside a Garrick workspace.", file=sys.stderr)
        return 1
    rel = lambda p: _rel(root, p)  # noqa: E731
    try:
        if args.command == "list":
            items = list_items(root)
            if args.json:
                print(json.dumps(items, indent=2))
            for i in ([] if args.json else items):
                print("\t".join((i["kind"], i["zone"], i["file"], i["date"], i["from"], i["subject"])).rstrip("\t"))
        elif args.command == "parse":
            print(json.dumps(parse(root, Path(args.file)), indent=2))
        elif args.command == "file-conversation":
            slug, dest, page = file_conversation(root, Path(args.file), _tags(args.parties), args.title, args.date,
                                                 args.today)
            print("%s\t%s\t%s" % (slug, rel(dest), rel(page)))
        elif args.command == "file-reading":
            slug, dest, page = file_reading(root, Path(args.file), args.title, args.slug, args.today)
            print("%s\t%s\t%s" % (slug, rel(dest), rel(page)))
        elif args.command == "file-to-project":
            print(rel(file_to_project(root, Path(args.file), args.project, _tags(args.parties), args.name)))
        elif args.command == "extract-attachment":
            how, dest = extract_attachment(root, args.mail, args.project, args.name, args.index, args.save_as)
            print("%s\t%s" % (how, rel(dest)))
        elif args.command == "learn":
            print("%s\t%s\t%s" % (learn(root, args.domain, args.party), args.domain.strip().lower(), strip_tag(args.party)))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
