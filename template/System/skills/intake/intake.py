#!/usr/bin/env python3
"""Mechanical steps for the intake skill: what is waiting, what it says, and
moving it to the place the skill chose.

Everything that comes in lands in an inbox first: a transcript in
`Wikis/Meetings/raw/inbox/`, and mail or any other file in a zone's `Inbox/`.
Whatever put it there (you, a mail rule, a script, your assistant's own
connector) decided nothing. Where it goes is decided by the rules, in
`System/rules.md`, and by whoever runs the skill. This script never decides it:
it lists, parses, suggests parties from mail domains as a hint, and files an
item only into the destination it is given, after checking the zone: the
wall is the zone's.

    python3 intake.py list [--json]                         everything waiting, in every inbox
    python3 intake.py parse --file FILE                     one item as JSON: headers, text, attachments, suggested parties
    python3 intake.py file-conversation --file FILE [--parties a,b] [--title "..."] [--date YYYY-MM-DD]
    python3 intake.py file-reading --file FILE [--title "..."] [--slug SLUG]
    python3 intake.py file-to-project --file FILE --project PATH [--parties a,b] [--name NAME] [--as-material]
    python3 intake.py extract-attachment --mail RAW --project PATH (--name NAME | --index N) [--save-as NAME]
    python3 intake.py file-note --file FILE [--destination "Acme, pricing"] [--title "..."]
    python3 intake.py process-notes [--tier sonnet] [--dry-run]     file the notes waiting, and update a thread when one warrants it (#572)
    python3 intake.py notes --project PATH [--thread NAME]  the notes since the thread's last wrap, and those awaiting review
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
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional, Tuple  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
sys.path.insert(0, str(HERE.parent / "meetings"))

from garrick_lib import (  # noqa: E402
    INBOX,
    MEDIA_EXTS,
    is_domain,
    is_own_address,
    is_webmail,
    knowledge_schema,
    landing,
    load_context,
    mail_attachments,
    move_new,
    parse_frontmatter,
    parse_mail,
    parse_mail_bytes,
    strip_recipients,
    parties_for_domain,
    split_domains,
    stamp_parties,
    strip_tag,
    always_asked,
    walled,
    workspace_root,
    write_new,
)
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
from ingest import (  # noqa: E402
    RAW_EXTS, Refusal, build_slug, filing, meetings_root, refuse_if_filed, source_id, taken_stems,
)

BODY_LIMIT = 50_000  # characters of text `parse` gives; the file keeps the rest
TEXT_EXTS = {".md", ".txt", ".csv", ".tsv", ".json", ".html", ".htm", ".vtt", ".xml", ".yaml", ".yml"}
SUBJECT_PREFIX_RE = re.compile(r"^\s*(?:re|fw|fwd|aw|wg|sv|vs|tr|rif|r)\s*(?:\[\d+\])?\s*:\s*", re.I)
KINDS = ("transcript", "mail", "file", "note", "unreadable")
WALL_REFUSAL = ("Refused: this came from a walled zone other than that project's. "
                "Nothing was moved. Tell the user only this, word for word: \"A wall holds some "
                "material back from this project, so I have not used it. Nothing was written.\"")


# --------------------------------------------------------------------------- where


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def place_of(root: Path, path: Path) -> Tuple[str, str]:
    """("meetings", "") for the Meetings inbox, ("zone", <Zone>) for a zone's
    Inbox, ("workspace", "") for the workspace's own Inbox, where mail sent to
    one address for every zone waits for its zone. Refuses a file anywhere
    else: only an inbox is waiting to be filed."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        parts = ()
    if len(parts) == 4 and parts[0] == "Zones" and parts[2] == INBOX and not parts[1].startswith((".", "_")):
        return "zone", parts[1]
    if len(parts) == 2 and parts[0] == INBOX:
        return "workspace", ""
    if len(parts) == 5 and parts[:4] == ("Wikis", "Meetings", "raw", "inbox"):
        return "meetings", ""
    raise Refusal("%s is not in an inbox: %s/, Zones/<Zone>/%s/ or Wikis/Meetings/raw/inbox/." % (path.name, INBOX, INBOX))


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
    if ext in (".md", ".txt") and read_note(path) is not None:
        return "note", None
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


FIRST_ZONE = ("%s waits in the workspace's Inbox, which belongs to no zone. Settle its zone with the user first, "
              "then move it there with move-to-zone and file it from that zone's inbox.")

# What the mail fetcher names a message from an address kept for reading.
READING_PREFIX = "reading-"
SKIPPED_LOG = ".skipped.log"


def skip(root: Path, path: Path, reason: str, today: Optional[str] = None) -> str:
    """Take an item out of a zone's Inbox without filing it, because it is too
    thin to keep: a one-line promotion, an empty notice. It is gone from the
    Inbox, and one line in the Inbox's .skipped.log, never committed, says
    what it was and why. Only from a zone's Inbox; never a transcript."""
    path, where, zone, kind, m = _item(root, path)
    if where not in ("zone", "workspace"):
        raise Refusal("%s is a transcript waiting in the Meetings inbox; a conversation is never skipped." % path.name)
    if kind == "transcript":
        raise Refusal("%s is a transcript, a conversation, and a conversation is never skipped." % path.name)
    reason = " ".join((reason or "").split())
    if not reason:
        raise Refusal("Say why it is skipped, in a few words: --reason thin.")
    subject = (m or {}).get("subject") or ""
    sender = ", ".join(_fmt((m or {}).get("from") or []))
    today = today or datetime.date.today().isoformat()
    log = (root / "Zones" / zone if zone else root) / INBOX / SKIPPED_LOG
    with log.open("a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\t%s\t%s\n" % (today, path.name, sender, subject, reason[:200]))
    path.unlink()
    return "Skipped %s (%s)." % (subject or path.name, reason)


def _describe_note(item: dict, path: Path) -> None:
    """A note's row: where it came by, its date and its first words, and the destination it names, if any."""
    if item["kind"] != "note":
        return
    info = read_note(path) or {}
    item.update({"date": note_date(info.get("date", ""), ""), "from": info.get("via", ""),
                 "subject": info.get("title") or first_words(info.get("text", "")),
                 "destination": info.get("destination", "")})


def _flag_claim(item: dict, path: Path) -> None:
    """A file that says it is the owner's note and that no channel recorded stays an ordinary item, and says so."""
    if item["kind"] != "note" and claimed_note(path) is not None:
        item["claim"] = "unproved"


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
    ctx = None
    for p in _waiting(root / INBOX):
        kind, m = kind_of(p, "workspace")
        item = {"kind": kind, "zone": "", "file": _rel(root, p), "date": "", "from": "", "subject": ""}
        _describe_note(item, p)
        _flag_claim(item, p)
        if p.name.startswith(READING_PREFIX):
            item["route"] = "reading"
        if m:
            ctx = ctx or load_context(root)
            item.update({"date": m["date"] or "", "from": ", ".join(_fmt(m["from"])), "subject": m["subject"],
                         "suggested_zone": zone_for(ctx, suggest(ctx, "", m))[0]})
        rest.append(((m or {}).get("sent") or "9999", "", p.name, item))
    for zone in _zones(root):
        for p in _waiting(zone / INBOX):
            kind, m = kind_of(p, "zone")
            item = {"kind": kind, "zone": zone.name, "file": _rel(root, p), "date": "", "from": "", "subject": ""}
            _describe_note(item, p)
            _flag_claim(item, p)
            if p.name.startswith(READING_PREFIX):
                item["route"] = "reading"            # fetched from an address kept for reading
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


def _zone_of_party(ctx: dict, tag: str) -> str:
    return ((ctx["parties"].get(tag) or {}).get("zone") or "").strip()


def _walled_zone(ctx: dict, tag: str) -> str:
    """The walled zone a party sits in, or "" when its zone is open, or it has none the table knows."""
    zone = _zone_of_party(ctx, tag)
    return zone if zone and walled(ctx, zone) else ""


def suggest(ctx: dict, zone: str, mail: dict) -> dict:
    """Which parties a mail's addresses point to, and when to ask. A hint only.

    Domains are matched against the Domains column of Parties. A plus tag
    (`you+acme@...`) that is a party's tag is a strong hint, on any domain.
    Personal webmail never names a party by itself. Addresses inside a message
    forwarded or quoted inline count like the rest. The hint says to ask when
    nothing matches, when a domain belongs to two parties, when the parties on
    the mail sit in two walled zones, when a party belongs to another
    zone, or for a party that is always asked about. It never says where the mail goes: the user answers which zone.

    The user's own addresses (the Me section of context.md) carry mail; they
    do not say whose it is. Their plus tags still count, but their domains
    never raise a question. The party an own address points to (an employer,
    say) is added only when it would not put a second walled party beside the
    ones the other addresses found, or when they found none, and is listed under
    `own` either way. It is never added to a mail in another zone's inbox. So
    a mail forwarded from a work account is read by what was forwarded.
    """
    addresses = []
    for key in ("from", "to", "cc", "delivered", "forwarded"):
        addresses += [addr for _, addr in mail.get(key, [])]
    plus, webmail, unknown, own_tags = [], [], [], []
    by_domain: Dict[str, List[str]] = {}
    for addr in addresses:
        local, _, domain = addr.rpartition("@")
        if "+" in local:
            tag = strip_tag(local.split("+", 1)[1])
            if tag in ctx["parties"] and tag not in plus:
                plus.append(tag)
        if is_own_address(ctx, addr):
            if not is_webmail(domain):
                own_tags += [t for t in parties_for_domain(ctx, domain) if t not in own_tags]
            continue
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
    if not parties and not any(len(t) > 1 for t in by_domain.values()):
        if webmail and not unknown and not own_tags:
            ask.append("It is from personal webmail (%s), which never names a party." % ", ".join(webmail))
        elif unknown:
            ask.append("No party has the domain %s." % ", ".join(unknown))
        elif not own_tags:
            ask.append("There is no address on it to go by.")
    found = sorted(parties)
    found_walled = {_walled_zone(ctx, f) for f in found} - {""}
    own_added = [t for t in own_tags if t not in parties
                 and not (_walled_zone(ctx, t) and found_walled - {_walled_zone(ctx, t)})
                 and (not zone or (ctx["parties"][t].get("zone") or zone).strip() == zone)]
    parties |= set(own_added)
    parties_list = sorted(parties)
    if not parties_list and not ask:
        ask.append("Only your own addresses are on it, and they do not say whose it is.")
    sides = sorted({_walled_zone(ctx, t) for t in parties_list} - {""})
    if len(sides) > 1:
        ask.append("Its parties sit in two walled zones, %s." % " and ".join(sides))
    for tag in parties_list:
        pzone = (ctx["parties"][tag].get("zone") or "").strip()
        if zone and pzone and pzone != zone:
            ask.append("%s is a %s party, but this mail is in the %s inbox." % (_name(ctx, tag), pzone, zone))
    senders = [addr for _, addr in mail.get("from", []) if not is_own_address(ctx, addr)]
    sender_domains = [addr.rpartition("@")[2] for addr in senders]
    for tag in parties_list:
        if always_asked(ctx, tag):
            ask.append("%s is a company with two hats here, and its name never says which." % _name(ctx, tag))
    # confirm is a return value: nothing proceeds on it without the user.
    return {"parties": parties_list, "ask": ask, "confirm": bool(ask),
            "plus": sorted(plus), "domains": by_domain,
            "unknown": unknown, "webmail": webmail, "own": {"tags": own_tags, "added": own_added},
            "sender_webmail": bool(sender_domains) and all(is_webmail(d) for d in sender_domains)}


def zone_for(ctx: dict, hint: dict) -> Tuple[str, str]:
    """(the zone a mail's parties point to, or "", and when "", why to ask),
    for mail sent to one address for every zone. The parties must all belong
    to one zone; none found, or parties from two zones, means asking."""
    zones = sorted({(ctx["parties"].get(t, {}).get("zone") or "").strip() for t in hint.get("parties", [])} - {""})
    if len(zones) == 1 and not hint.get("ask"):
        return zones[0], ""
    if len(zones) > 1:
        return "", "Its parties belong to %s." % " and ".join(zones)
    return "", (hint.get("ask") or ["Nothing on it says which zone."])[0]


def move_to_zone(root: Path, path: Path, zone: str) -> Path:
    """Move an item from the workspace's Inbox into a zone's, once the user
    has said which zone, so it is filed from there as any other. Never
    overwrites."""
    path, where, _, _, _ = _item(root, path)
    if where != "workspace":
        raise Refusal("%s is already in a zone's inbox, or in Meetings'; it moves only out of the workspace's %s/."
                      % (path.name, INBOX))
    match = [z for z in _zones(root) if z.name.lower() == (zone or "").strip().lower()]
    if not match:
        raise Refusal("There is no zone called %s. The zones are %s." % (zone, ", ".join(z.name for z in _zones(root))))
    dest = match[0] / INBOX / path.name
    if dest.exists():
        raise Refusal("%s already has a %s in its inbox; nothing was moved." % (match[0].name, path.name))
    dest.parent.mkdir(exist_ok=True)
    landing(root, match[0] / INBOX, dest)
    path.replace(dest)
    return dest


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
    if kind == "note":
        got = read_note(path) or {}
        info.update({"via": got.get("via", ""), "destination": got.get("destination", ""), "date": got.get("date", ""),
                     "from_owner": True, "title": note_title(got.get("text", ""), got.get("title", "")),
                     "text": got.get("text", "")[:BODY_LIMIT], "truncated": len(got.get("text", "")) > BODY_LIMIT})
        return info
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
        **({"suggested_zone": dict(zip(("zone", "ask"), zone_for(load_context(root), suggest(load_context(root), "", m))))}
           if where == "workspace" else {}),
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


def draft_page(title: str, date: str, zone: str, parties: List[str], slug: str, mail: dict, today: str,
               sid: str = "") -> str:
    when = datetime.date.fromisoformat(date)
    sender = _names(mail["from"]) or "an unknown sender"
    lines = ["---", "title: %s" % _yaml(title), "type: email", "date: %s" % date, "zone: %s" % zone]
    if parties:
        lines.append("parties: [%s]" % ", ".join(parties))      # an index of who it is about, never a wall
    lines += ["from: %s" % _yaml(", ".join(_fmt(mail["from"])))]
    lines += _block("to", _fmt(mail["to"]))
    lines += _block("cc", _fmt(mail["cc"]))
    lines += ["people: []", 'raw: "[[raw/%s]]"' % slug] + (["source-id: %s" % _yaml(sid)] if sid else [])
    lines += ["created: %s" % today, "updated: %s" % today, "---", ""]
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
    """The party tags given, an index and never a wall: none is fine; one the Parties table does not hold is a typo."""
    tags = sorted(dict.fromkeys(strip_tag(t) for t in parties if strip_tag(t)))
    unknown = [t for t in tags if t not in ctx["parties"]]
    if unknown:
        raise Refusal("%s is not a party tag in System/context.md; add the party first." % ", ".join(unknown))
    return tags


def _refuse_other_walled_zone(ctx: dict, zone: str, tags: List[str], what: str) -> None:
    """A party of a walled zone other than the item's own is a question for the user, not a filing."""
    other = sorted({_walled_zone(ctx, t) for t in tags} - {"", zone})
    if other:
        raise Refusal("%s names a party of the walled zone %s, but it is in the %s inbox. Ask the user which zone it "
                      "belongs to; a conversation for two walled zones is split by zone first." % (what, " and ".join(other), zone))


def _page_then(root: Path, home: Path, page: Path, text: str, place) -> None:
    """Write a draft page, then file the item it describes with `place()`.
    When filing is refused, the page is taken back, so the item stays in its
    inbox and nothing is left half-filed."""
    write_new(root, home, page, text.encode("utf-8"))
    try:
        place()
    except BaseException:
        page.unlink()  # removes the page itself, never what a link points to
        raise


def file_conversation(root: Path, path: Path, parties: List[str], title: str = "", date: str = "",
                      today: Optional[str] = None, confirmed: bool = False) -> Tuple[str, Path, Path]:
    """Record a mail from a zone's Inbox as a conversation: move the original,
    untouched, into `Wikis/Meetings/raw/` and write its draft page beside the
    meeting pages, with the zone it was dropped in and the parties given, an
    index and never a wall.

    Refuses anything but mail in a zone Inbox, a party the table does not
    hold, a party of another walled zone, and a mail with no date or title to
    go by. A mail whose addresses name a party of a walled zone other than the
    inbox's, or that name no party while none is given, is a question for the
    user (`Confirm`): the filing goes on only when the user has answered
    (`confirmed`). Never overwrites. Returns (slug, raw path, page path).
    """
    path, where, zone, kind, m = _item(root, path)
    if where == "workspace":
        raise Refusal(FIRST_ZONE % path.name)
    if where != "zone":
        raise Refusal("%s is in the Meetings inbox; a transcript is landed with the meetings skill's ingest.py land."
                      % path.name)
    if kind != "mail":
        raise Refusal("%s is not a mail. A transcript or call notes are landed with ingest.py land; "
                      "anything else goes to Knowledge or a project." % path.name)
    ctx = load_context(root)
    tags = _known_tags(ctx, parties, "A mail")
    _refuse_other_walled_zone(ctx, zone, tags, "This mail")
    mail = m or parse_mail(path)
    if path.suffix.lower() == ".eml" and not confirmed:
        # what its addresses name, whatever parties were given: another walled zone's is the user's question, and so
        # is a mail whose addresses settle nothing when no party was given
        hint = suggest(ctx, zone, mail)
        other = sorted({_walled_zone(ctx, t) for t in hint["parties"]} - {"", zone})
        if other:
            raise Confirm("Needs your answer first: the mail's addresses name a party of the walled zone %s, but it is in "
                          "the %s inbox. Nothing was filed." % (" and ".join(other), zone))
        if not tags and hint["ask"]:
            raise Confirm("Needs your answer first: %s Nothing was filed." % hint["ask"][0])
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
    refuse_if_filed(root, path)
    slug = build_slug(date, title, taken_stems(meetings_root(root), "raw", "wiki/sources"))
    dest = raw_dir / (slug + path.suffix.lower())
    page = sources / (slug + ".md")
    meetings = meetings_root(root)
    today = today or datetime.date.today().isoformat()
    text = draft_page(title, date, zone, tags, slug, mail, today, source_id(path))
    with filing(root):
        landing(root, meetings, dest)
        _page_then(root, meetings, page, text, lambda: move_new(root, meetings, path, dest))
    return slug, dest, page


# --------------------------------------------------------------------------- file something to read


def reading_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _name_part(text: str) -> str:
    """A piece of a raw file's name, from a title or a publisher: no folder
    separators or characters a file name cannot hold, spaces kept."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", text or "")
    return re.sub(r"\s+", " ", text).strip(" .")[:120]


def raw_place(kroot: Path, schema: dict, slug: str, ext: str, kind: str, date: str, publisher: str,
              title: str) -> Path:
    """Where the original goes, by the wiki's raw pattern."""
    pattern = schema["raw"]
    if "{kind}" in pattern:
        if not kind:
            raise Refusal("This Knowledge wiki keeps its originals by kind; pass --kind, one of %s."
                          % ", ".join(schema["kinds"]))
        if kind not in schema["kinds"]:
            raise Refusal("%s is not a kind this Knowledge wiki keeps; its kinds are %s." % (kind, ", ".join(schema["kinds"])))
    values = {"slug": slug, "ext": ext.lstrip("."), "kind": kind, "date": date,
              "publisher": _name_part(publisher) or "Unknown", "title": _name_part(title) or slug}
    rel = re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], pattern)
    return kroot / rel


def file_reading(root: Path, path: Path, title: str = "", slug: str = "",
                 today: Optional[str] = None, shelf: str = "") -> Tuple[str, Path, Path]:
    """Freeze an item from a zone's Inbox into `Wikis/Knowledge/raw/` and write a
    draft source page for the knowledge skill to finish. A mail is frozen with
    the reader's own addresses removed (`strip_recipients`); anything else is
    moved untouched.

    The page carries no zone and no parties: Knowledge holds published
    material, usable anywhere. Refuses audio, a transcript, and a slug already
    used; never overwrites. Returns (slug, raw path, page path).
    """
    path, where, zone, kind, m = _item(root, path)
    if where not in ("zone", "workspace"):          # reading carries no zone: it may come straight from the workspace's
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
    if slug in taken_stems(kroot, "raw", "wiki/sources"):
        raise Refusal("%s is already used in Knowledge. If this is a different item, pass --slug with a "
                      "distinguishing word, not a number." % slug)
    schema, _ = knowledge_schema(root)
    page = sources / (slug + ".md")
    today = today or datetime.date.today().isoformat()
    sender = _names(mail["from"]) if mail else ""
    dest = raw_place(kroot, schema, slug, path.suffix.lower(), shelf, (mail and mail["date"]) or today, sender, title)
    if dest.exists():
        raise Refusal("%s is already in Knowledge. If this is a different item, pass --title or --slug with a "
                      "distinguishing word, not a number." % dest.relative_to(kroot))
    if mail:
        author = _yaml(sender) if sender else "<who wrote or published it>"
        published = mail["date"] or "<YYYY-MM-DD, or YYYY-MM, or YYYY>"
        how = "Arrived by mail%s%s." % (" from %s" % sender if sender else "",
                                       ", %s" % mail["date"] if mail["date"] else "")
    else:
        author, published = "<who wrote or published it>", "<YYYY-MM-DD, or YYYY-MM, or YYYY>"
        how = "Dropped into the %s inbox as %s." % (zone or "workspace's", path.name)
    known = {"author": author, "published": published,
             "raw": '"[[%s]]"' % dest.relative_to(kroot).with_suffix("").as_posix()}
    fields = ["author", "published", "raw"] + [f for f in schema["source"]["fields"] if f not in ("author", "published", "raw")]
    text = "\n".join(
        ["---", "title: %s" % _yaml(title), "type: %s" % schema["source"]["type"]]
        + ["%s: %s" % (f, known.get(f, "<%s>" % f.replace("-", " "))) for f in fields]
        + ["confidence: <high, medium or low>", "created: %s" % today,
           "updated: %s" % today, "---", "", "# %s" % title, "", how, "",
           "<A short summary. Every vendor claim attributed to its vendor.>", "",
           "Touches <the concept and entity pages it speaks to>.", ""])
    frozen = None
    if mail:
        own = load_context(root).get("me", [])
        frozen = strip_recipients(path.read_bytes(), path.suffix, own)
        left = parse_mail_bytes(frozen, path.suffix)
        named = [a for _, a in left["to"] + left["cc"] + left["delivered"]]
        named += [a for a in own if a in frozen.decode("utf-8", errors="replace").lower()]
        if named:
            raise Refusal("%s still names who received it (%s) after its recipients were taken out, so it is "
                          "not filed in Knowledge. Save it as .eml and file that instead." % (
                              path.name, ", ".join(sorted(set(named)))))

    def freeze():
        if mail:
            write_new(root, kroot, dest, frozen)
            path.unlink()
        else:
            move_new(root, kroot, path, dest)
    with filing(root):
        dest.parent.mkdir(parents=True, exist_ok=True)
        landing(root, kroot, dest)
        _page_then(root, kroot, page, text, freeze)
    return slug, dest, page


# --------------------------------------------------------------------------- file into a project


def resolve_project(root: Path, project: Optional[str]) -> Tuple[Path, str]:
    """(folder, zone) of the project named by an explicit path,
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
    return p, parts[1]


class Confirm(Refusal):
    """A question the user must answer first: nothing is filed. The question goes back to the caller, who shows it to
    the user; the filing goes on only when the user has answered (`confirmed`)."""


def _safe_name(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name.strip().lstrip(".")
    name = re.sub(r"[\x00-\x1f:]", " ", name).strip()
    if not name:
        raise Refusal("That file name is empty once unsafe characters are removed; pass a name.")
    return name


def file_to_project(root: Path, path: Path, project: Optional[str], parties: List[str], name: str = "",
                    as_material: bool = False, confirmed: bool = False) -> Path:
    """Move a dropped file from a zone's Inbox into the named project's `Sources/`.

    The destination is only ever the one given. Refuses without a project, a
    project in another zone, a project whose party is walled from `parties`,
    mail (a mail is recorded as a conversation first, and only its attachment
    goes to the project), audio, a name already taken, and a symbolic link
    between the workspace and the destination. Returns the new path.

    With `as_material`, a mail the user said is material and not a
    conversation is saved whole, after the same checks. A `.eml` gets one
    header first, `X-Garrick-Parties`, so the walls can read its parties
    without a Meetings page. The flag changes nothing for any other item.
    """
    path, where, zone, kind, _ = _item(root, path)
    folder, pzone = resolve_project(root, project)
    if where == "workspace":
        raise Refusal(FIRST_ZONE % path.name)
    if where != "zone":
        raise Refusal("%s is in the Meetings inbox, which holds conversations, never project material." % path.name)
    if kind == "mail" and not as_material:
        raise Refusal("%s is a mail. File it as a conversation first (file-conversation), then save its attachment "
                      "with extract-attachment. Only when the user said the mail itself is material for the project, "
                      "not a conversation, pass --as-material." % path.name)
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
    if kind == "mail" and path.suffix.lower() == ".eml" and not confirmed:
        # the parties its addresses carry: any in a walled zone other than the project's is the user's question
        hint = suggest(ctx, zone, parse_mail_bytes(path.read_bytes()))
        other = sorted({_walled_zone(ctx, t) for t in hint["parties"]} - {"", pzone})
        if other:
            raise Confirm("Needs your answer first: the mail's addresses name a party of the walled zone %s. "
                          "Nothing was filed." % " and ".join(other))
    _refuse_other_walled_zone(ctx, pzone, tags, "This file")
    dest = folder / "Sources" / _safe_name(name or path.name)
    with filing(root):
        landing(root, folder, dest)
    if dest.exists():
        raise Refusal("%s already exists; pass --name for a different one." % _rel(root, dest))
    with filing(root):
        if kind == "mail" and path.suffix.lower() == ".eml":
            write_new(root, folder, dest, stamp_parties(path.read_bytes(), tags) if tags else path.read_bytes())
            path.unlink()
        else:
            move_new(root, folder, path, dest)
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
    if not fm.get("zone"):
        raise Refusal("%s has no finished page with its zone; file the mail as a conversation first."
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
    folder, pzone = resolve_project(root, project)
    if fm.get("zone") != pzone:
        raise Refusal("That mail is in the %s zone but %s is in %s. Zones never mix." % (fm.get("zone"), folder.name, pzone))
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
    with filing(root):
        landing(root, folder, dest)
    if dest.exists():
        if dest.read_bytes() == chosen[2]:
            return "already", dest
        raise Refusal("%s already exists and is different; pass --save-as for another name." % _rel(root, dest))
    with filing(root):
        write_new(root, folder, dest, chosen[2])
    return "saved", dest


# --------------------------------------------------------------------------- learn


# --------------------------------------------------------------------------- notes to yourself (#569)

NOTES = "Notes"                    # the folder a note lands in, under its thread (or its one-thread project)
NOTE_WORDS = 6                    # words of a note that make its title, and name it in a question
FRONT_RE = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S)
# What reads as something the owner owes: a line that opens with a marker, or with a verb of doing. Nothing else in
# a note is taken for an action: the rest stays text.
OWE_MARK = re.compile(r"^(?:[-*]\s*(?:\[ \]\s*)?)?(?:todo|to do|to-do|action|task|remember to|remind me to|"
                      r"i (?:need|have|must|ought) to|need to|must)\b\s*:?\s*(.+)$", re.I)
OWE_VERB = re.compile(r"^(?:[-*]\s*(?:\[ \]\s*)?)?((?:call|phone|email|e-mail|mail|send|ask|book|schedule|review|"
                      r"follow up with|chase|draft|write|pay|order|buy|confirm|prepare|share|update|fix|check|"
                      r"ping|text|reply to|forward|file|sign|renew|cancel|arrange|organise|organize)\b.{2,})$", re.I)


def split_front(text: str) -> Tuple[dict, str]:
    """(frontmatter, body) of a note: the body is everything after the closing line, as it was written."""
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    from garrick_lib import parse_frontmatter_text
    return parse_frontmatter_text("---\n%s\n---\n" % m.group(1)), m.group(2)


LEDGER = ("System", "notes-ledger.json")


def inbox_root(path: Path) -> Optional[Path]:
    """The workspace an inbox file sits in: its parent is an `Inbox/`, the workspace's or a zone's. None for any
    other place."""
    path = Path(path)
    if path.parent.name != "Inbox":
        return None
    top = path.parent.parent
    return top.parent.parent if top.parent.name == "Zones" else top


def ledger_path(root: Path) -> Path:
    return Path(root).joinpath(*LEDGER)


def load_ledger(root: Path) -> dict:
    """The notes ledger: {"notes": {inbox path: {"id", "sha256"}}, "reported": [hashes]}. A ledger that is missing,
    unreadable or not in this shape is empty, so it trusts nothing."""
    try:
        data = json.loads(ledger_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else {}
    reported = data.get("reported") if isinstance(data.get("reported"), list) else []
    return {"notes": {k: v for k, v in notes.items() if isinstance(v, dict)}, "reported": [r for r in reported if isinstance(r, str)]}


def _update_ledger(root: Path, change) -> None:
    """Read the ledger, let `change` edit it, write it back through a temporary file and a rename, under a lock
    that the writers share (the Telegram receiver, and the step that reports a claim)."""
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with open(str(lock), "a") as handle:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        data = load_ledger(root)
        change(data)
        tmp = path.with_name(path.name + ".new")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(path))


def record_note(root: Path, path: Path, note_id: str = "") -> None:
    """A channel that wrote a note into an inbox records it here: the note's id and the hash of the file as it was
    written. Only a note the ledger holds, unchanged, is the owner's (#584)."""
    path = Path(path)
    rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    def change(data: dict) -> None:
        data["notes"] = {k: v for k, v in data["notes"].items() if (Path(root) / k).is_file()}
        data["notes"][rel] = {"id": str(note_id), "sha256": digest}
    _update_ledger(root, change)


def proved(path: Path, data: Optional[bytes] = None) -> bool:
    """Whether the ledger holds this inbox file with the bytes it was written with. `data` is the bytes the caller
    already read: they are hashed as given, so what is parsed and what is hashed are the same bytes."""
    root = inbox_root(Path(path).resolve())
    if root is None:
        return False
    try:
        if data is None:
            data = Path(path).read_bytes()
        entry = load_ledger(root)["notes"].get(Path(path).resolve().relative_to(root).as_posix())
        return bool(entry) and entry.get("sha256") == hashlib.sha256(data).hexdigest()
    except (OSError, ValueError):
        return False


def claimed_note(path: Path, data: Optional[bytes] = None) -> Optional[dict]:
    """What a file in an inbox says it is, a note from the owner: `kind: note` and `from-owner: true` in its
    frontmatter. It says nothing of who wrote it: `read_note` checks that."""
    if path.suffix.lower() not in (".md", ".txt"):
        return None
    try:
        data = path.read_bytes() if data is None else data
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    front, body = split_front(data.decode("utf-8", errors="replace"))
    if str(front.get("kind") or "").strip().lower() != "note":
        return None
    if str(front.get("from-owner") or "").strip().lower() != "true":
        return None
    return {"via": str(front.get("via") or "").strip(), "destination": str(front.get("destination") or "").strip(),
            "date": str(front.get("date") or "").strip(), "text": body.strip("\n"), "title": str(front.get("title") or "").strip()}


def read_note(path: Path) -> Optional[dict]:
    """The note a file in an inbox is, or None. A channel that checked the sender (the Telegram receiver) writes
    `kind: note` and `from-owner: true` in the frontmatter and records the file in the notes ledger. An item is a
    note only when both lines are there and the ledger holds the file unchanged (#584): any other file is sorted as
    it always was, whatever else it says."""
    try:
        data = Path(path).read_bytes()              # read once: the same bytes are parsed and hashed
    except OSError:
        return None
    got = claimed_note(path, data)
    return got if got is not None and proved(path, data) else None


def unproved_claims(root: Path) -> List[str]:
    """The files waiting in the inboxes that claim to be the owner's note and that no channel recorded."""
    out = []
    for folder in [Path(root) / INBOX] + [z / INBOX for z in _zones(Path(root))]:
        for p in _waiting(folder):
            if claimed_note(p) is not None and not proved(p):
                out.append(_rel(root, p))
    return out


def report_unproved(root: Path) -> List[str]:
    """The claims `unproved_claims` finds that were not reported before, each once: the ledger keeps the hash of
    what it reported."""
    fresh: List[str] = []

    def change(data: dict) -> None:
        for rel in unproved_claims(root):
            digest = hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()
            if digest not in data["reported"]:
                data["reported"].append(digest)
                fresh.append(rel)
        data["reported"] = data["reported"][-200:]
    if unproved_claims(root):
        _update_ledger(root, change)
    return fresh


def first_words(text: str, most: int = NOTE_WORDS) -> str:
    words = re.sub(r"[#*_`>\[\]|]", " ", text or "").split()
    return " ".join(words[:most])


def note_title(text: str, given: str = "") -> str:
    """A note's title: the one given, or its first words; safe as a file name."""
    title = " ".join((given or first_words(text)).split())
    title = re.sub(r'[\x00-\x1f:/\\"<>|?*]', " ", title)
    title = " ".join(title.split()).strip(" .")[:60].strip(" .")
    return title or "Note"


def owed(text: str) -> List[str]:
    """The lines of a note that read as something the owner owes, as plain action text. Only a marker
    (`todo:`, `remind me to`, a checkbox) or a verb of doing at the start of a line counts."""
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or len(line) > 300:
            continue
        m = OWE_MARK.match(line) or OWE_VERB.match(line)
        if m:
            out.append(" ".join(m.group(1).split()).rstrip("."))
    seen, kept = set(), []
    for line in out:
        if line.casefold() not in seen:
            seen.add(line.casefold())
            kept.append(line)
    return kept[:5]


_MODS: Dict[str, object] = {}


def _extra_module(root: Path, name: str):
    """One of the status extra's modules (ask.py, ask_scope.py), the ones Ask uses to settle a spoken name: the
    workspace's own copy, or, in a Garrick clone, the one under extras/. None where there is none: a destination
    cannot then be settled here, and the note waits to be asked about."""
    key = "%s|%s" % (root, name)
    if key not in _MODS:
        found = None
        places = [Path(root) / "System" / "status" / name]
        clone = HERE.parents[3]
        if (clone / "template" / "System" / "skills" / "intake").is_dir():
            places.append(clone / "extras" / "status" / name)
        for src in places:
            if not src.is_file():
                continue
            mod_name = "garrick_intake_%s_%d" % (src.stem, abs(hash(str(src))))
            try:
                spec = importlib.util.spec_from_file_location(mod_name, str(src))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)
                found = mod
                break
            except Exception:
                sys.modules.pop(mod_name, None)
        _MODS[key] = found
    return _MODS[key]


def _live_threads(folder: Path) -> List[str]:
    out = []
    threads = folder / "Threads"
    if threads.is_dir():
        for t in sorted(p for p in threads.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            if (t / (t.name + ".md")).is_file():
                out.append(t.name)
    return out


def _said(project: str, thread: Optional[str]) -> str:
    return "%s, %s" % (project, thread) if thread else project


def _which(options: List[str]) -> str:
    return ", ".join(options[:-1]) + " or " + options[-1] if len(options) > 1 else options[0]


class NoPlace(Confirm):
    """A purpose="ask" question for a name that settled to no place. `offer` is the places it lists, when it lists any."""

    def __init__(self, text: str, offer: Optional[List[dict]] = None):
        super().__init__(text)
        self.offer = offer or []


def _party_candidates(root: Path, scope, lib_, names: dict, found) -> List[dict]:
    """The places a party's name could mean: the live threads of the projects that carry the party's tag, in the
    party's own zone only, three at most, as places the dispatcher can bind to."""
    out = []
    tags = set().union(*(e.parties for e in found.entries if e.kind == "party")) if found.entries else set()
    zones = {e.zone for e in found.entries if e.kind == "party" and e.zone}
    for zone, projects in names.items():
        if zone not in zones:
            continue
        for project, rec in projects.items():
            if not (scope.place_parties(root, zone, project, None, lib_) & tags):
                continue
            for thread in (sorted(rec["threads"]) or [None]):
                out.append({"zone": zone, "project": project, "thread": thread, "said": _said(project, thread)})
    return out[:3]


def resolve_destination(root: Path, spoken: str, about: str = "", purpose: str = "note") -> dict:
    """Where a note goes, from the words it was given: {"zone", "project", "thread" (or None), "folder", "said"}.

    The words are settled as Ask settles any name, by ask_scope.mentions(): the Parties, People and Aliases of
    context.md, a project's or a thread's name and its spoken form. Nothing is guessed. A name that fits two
    places, or none, comes back as a question (Confirm) and nothing is filed; a destination in two zones is
    refused, as a note is about one place; a project that holds several threads asks which thread.

    `purpose="ask"` is for a question about a place, not a note (the Telegram channel's dispatcher): the questions
    are worded without "note", a name that settled to nothing but a party lists the party's places, and a project
    alone is enough: with one live thread it settles to that thread, with several to the project (thread None)."""
    asking = purpose == "ask"
    if asking:
        ask_q = "Which thread?"
    else:
        ask_q = "Where does the note about %s go?" % (first_words(about) or "this")
    spoken = " ".join((spoken or "").split())
    if not spoken:
        raise (NoPlace(ask_q) if asking else Confirm(ask_q))
    ask, scope = _extra_module(root, "ask.py"), _extra_module(root, "ask_scope.py")
    if ask is None or scope is None:
        raise Confirm("%s A spoken name can be settled only with the status extra installed." % ask_q)
    lib_ = scope.lib(root)
    if lib_ is None:
        raise (NoPlace(ask_q) if asking else Confirm(ask_q))
    names = ask.scan(root)
    ctx = load_context(root)
    found = scope.mentions(root, spoken, names, ctx, lib_)
    if found.question:
        raise Confirm(found.question)
    places = found.places
    if not places:
        if asking:
            offer = _party_candidates(root, scope, lib_, names, found)
            if offer:
                raise NoPlace("Which thread do you mean: %s?" % _which([o["said"] for o in offer]), offer)
            raise NoPlace(ask_q)
        raise Confirm(ask_q)
    zones = sorted({z for z, _, _ in places})
    if len(zones) > 1 and asking:
        raise Refusal("That names places in two zones, %s. Say one." % " and ".join(zones))
    if len(zones) > 1:
        raise Refusal("The destination names places in two zones, %s. A note is about one place: say one, and "
                      "nothing was filed." % " and ".join(zones))
    zone = zones[0]
    threads = sorted({(p, t) for _, p, t in places if t})
    projects = sorted({p for _, p, t in places if not t})
    if len(threads) > 1:
        if asking:
            raise Confirm("Which thread do you mean: %s?" % _which([_said(p, t) for p, t in threads]))
        raise Confirm("Which thread is the note about: %s?" % _which([_said(p, t) for p, t in threads]))
    if threads:
        project, thread = threads[0]
        if any(p != project for p in projects):
            if asking:
                raise Confirm("Which one do you mean: %s?" % _which([_said(p, None) for p in sorted(set(projects) | {project})]))
            raise Confirm("Which place is the note about: %s?" % _which([_said(p, None) for p in sorted(set(projects) | {project})]))
    else:
        if len(projects) > 1:
            if asking:
                raise Confirm("Which project do you mean: %s?" % _which(projects))
            raise Confirm("Which project is the note about: %s?" % _which(projects))
        project, thread = projects[0], None
        many = _live_threads(root / "Zones" / zone / project)
        if asking and len(many) == 1:
            thread = many[0]                     # one live thread: the question is about that thread
        elif many and not asking:
            raise Confirm("Which thread of %s is the note about: %s?" % (project, _which(many)))
    folder = root / "Zones" / zone / project
    if thread:
        folder = folder / "Threads" / thread
    if not (folder / (folder.name + ".md")).is_file():
        if asking:
            raise Refusal("%s has nothing to read yet." % _said(project, thread))
        raise Refusal("%s has no note of its own, so there is nowhere to put a note." % _said(project, thread))
    return {"zone": zone, "project": project, "thread": thread, "folder": folder, "said": _said(project, thread)}


def place_for(root: Path, zone: str, project: str, thread: Optional[str] = None) -> dict:
    """The place a note goes when the caller has settled it already (the Ask box checked the names against the live
    list): the same answer resolve_destination() gives, from the folders. Refuses a place that is not there, and a
    project with threads and no thread named."""
    if not zone or not project or any(("/" in x or "\\" in x or x.startswith((".", "_"))) for x in (zone, project, thread or "a")):
        raise Refusal("That is not a place a note can go.")
    folder = root / "Zones" / zone / project
    if thread is None:
        many = _live_threads(folder)
        if many:
            raise Refusal("Which thread of %s is the note about: %s?" % (project, _which(many)))
    else:
        folder = folder / "Threads" / thread
    if not (folder / (folder.name + ".md")).is_file():
        raise Refusal("%s has no note of its own, so there is nowhere to put a note." % _said(project, thread))
    return {"zone": zone, "project": project, "thread": thread, "folder": folder, "said": _said(project, thread)}


def _label_for(zone: Path, project: str, thread: Optional[str]) -> str:
    """The `[[...]]` a Todo line opens with: the thread's name, the project's for a one-thread project, with the
    note's path where another note in the zone has the same name."""
    name = thread or project
    note = zone / project / ("Threads/%s" % thread if thread else "") / (name + ".md")
    same = 0
    for _, dirnames, files in os.walk(str(zone)):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_")) and d != "archive"]
        same += sum(1 for f in files if f.lower() == (name + ".md").lower())
    if same <= 1:
        return name
    return "%s|%s" % (note.relative_to(zone).with_suffix("").as_posix(), name)


def _todo_module():
    spec = importlib.util.spec_from_file_location("garrick_intake_todo", str(HERE.parent / "todo" / "todo.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plain(line: str) -> str:
    body = re.sub(r"\s*·\s*\[[^\]]*\]\([^)\s]*\)", "", line[6:] if line.startswith("- [") else line)
    body = re.sub(r"\s*(?:📅|⏳|🛫)️?\s*\d{4}-\d{2}-\d{2}", "", body)
    return re.sub(r"\s+", " ", body).strip().rstrip(".!").casefold()


def add_todo(zone: Path, label: str, text: str, source: Tuple[str, str]) -> bool:
    """One open line at the top of the Todo list's Inbox, in the list's own shape, with the note as its source:
    `- [ ] [[Thread]]: text · [title](path)`. False when the list already holds the action."""
    tl = _todo_module()
    lines = tl.read(zone)
    line = "- [ ] [[%s]]: %s · [%s](%s)" % (label, text, source[0].replace("]", ")").replace("[", "("),
                                          source[1].replace(" ", "%20"))
    mine = _plain(line)
    if any(l.startswith("- [ ] ") and _plain(l) == mine for l in lines):
        return False
    span = tl.sections(lines).get("Inbox")
    if span is None:
        raise Refusal("%s's Todo.md has no Inbox section." % zone.name)
    start, end = span
    body = [l for l in lines[start:end] if l.strip() != "*Nothing recorded yet.*"]
    j = 0
    while j < len(body) and not body[j].strip():
        j += 1
    k = j
    while k < len(body) and body[k].strip() and not body[k].startswith("- ["):
        k += 1                                   # the description paragraph
    desc, rest = body[j:k], body[k:]
    while rest and not rest[0].strip():
        rest.pop(0)
    new = [""] + (desc + [""] if desc else []) + [line] + rest
    if new[-1].strip():
        new.append("")                           # a blank line before the next heading
    lines[start:end] = new
    tl.write(zone, lines)
    return True


def note_text(text: str, via: str, created: str, review: bool = False) -> str:
    head = ["---", "kind: note"]
    if review:
        head.append("review: pending")        # the processor could not take it for a decision (#572): the owner decides
    if via:
        head.append("via: %s" % _yaml(via))
    head += ["created: %s" % _yaml(created), "---", ""]
    return "\n".join(head) + text.strip("\n") + "\n"


def note_date(value: str, today: str) -> str:
    """YYYY-MM-DD of a note: its own date when it carries one, else today."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", value or "")
    return m.group(0) if m else today


def add_note(root: Path, place: dict, text: str, title: str = "", via: str = "", date: str = "",
             today: Optional[str] = None, review: bool = False) -> dict:
    """Write one note into the place `resolve_destination` settled, and the actions it holds into that zone's
    Todo.md. Returns {"note": Path, "todo": [lines added], "todo_file": Path or None, "before": the Todo.md's
    bytes before}. It writes nothing else: the thread's note, its Resume here block and every rule stay as they
    are. The text is a note's own and runs nothing."""
    today = today or datetime.date.today().isoformat()
    text = (text or "").strip()
    if not text:
        raise Refusal("There is nothing in the note.")
    if len(text) > BODY_LIMIT:
        raise Refusal("The note is longer than %d characters." % BODY_LIMIT)
    day = note_date(date, today)
    stamp = datetime.date.fromisoformat(day).strftime("%y%m%d")
    name = note_title(text, title)
    folder = place["folder"] / NOTES
    zone = root / "Zones" / place["zone"]
    target = folder / ("%s - %s.md" % (stamp, name))
    n = 1
    while target.exists():
        n += 1
        target = folder / ("%s - %s (%d).md" % (stamp, name, n))
    created = date if re.match(r"\d{4}-\d{2}-\d{2}T", date or "") else datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    todo_file = zone / "Todo.md"
    before = todo_file.read_bytes() if todo_file.is_file() else None
    lines = owed(text)
    if lines and before is None:
        raise Refusal("%s has no Todo.md, so its actions cannot be listed." % place["zone"])
    landing(root, place["folder"], target)
    folder.mkdir(exist_ok=True)
    write_new(root, place["folder"], target, note_text(text, via, created, review).encode("utf-8"))
    added: List[str] = []
    label = _label_for(zone, place["project"], place["thread"]) if lines else ""
    for line in lines:
        if add_todo(zone, label, line, (target.stem, target.relative_to(zone).as_posix())):
            added.append(line)
    return {"note": target, "todo": added, "todo_file": todo_file if added else None, "before": before}


def file_note(root: Path, path: Path, destination: str = "", title: str = "", today: Optional[str] = None) -> Tuple[dict, dict]:
    """File a note waiting in an inbox: its destination resolved (the one given, else the note's own), the note
    written under that thread, its actions to that zone's Todo.md, and the inbox item removed. Refuses an item
    that is not a note (it needs `kind: note` and `from-owner: true`), asks when the destination does not
    settle, and refuses one in another zone than the zone inbox it waits in. Returns (what it wrote, the place)."""
    path, where, zone, kind, _ = _item(root, path)
    if where == "meetings":
        raise Refusal("%s is in the Meetings inbox, which holds conversations, never notes." % path.name)
    info = read_note(path) if kind == "note" else None
    if info is None:
        raise Refusal("%s is not a note: a note carries `kind: note` and `from-owner: true` in its frontmatter, "
                      "written by a channel that checked the sender and recorded it. Sort it as any other item." % path.name)
    place = resolve_destination(root, destination or info["destination"], info["text"])
    if where == "zone" and place["zone"] != zone:
        raise Refusal("%s is in the %s inbox but its destination is in %s. Zones never mix: move the note to the %s "
                      "inbox first if that is where it belongs." % (path.name, zone, place["zone"], place["zone"]))
    done = add_note(root, place, info["text"], title or info["title"], info["via"], info["date"], today)
    path.unlink()
    return done, place


def _notes_in(folder: Path) -> List[Path]:
    notes = folder / NOTES
    return sorted(p for p in notes.iterdir() if p.is_file() and p.suffix == ".md" and not p.name.startswith(".")) \
        if notes.is_dir() else []


def notes_since(root: Path, project: str, thread: Optional[str] = None) -> dict:
    """The notes of a thread (or of a one-thread project) since its last wrap, and those awaiting review. The
    last wrap is when the thread's note was last written: a note counts when it was made after that, or is marked
    `review: pending`."""
    folder, _ = resolve_project(root, project)
    place = folder / "Threads" / thread if thread else folder
    if thread and not place.is_dir():
        raise Refusal("%s has no thread %s." % (folder.name, thread))
    note = place / (place.name + ".md")
    wrapped = note.stat().st_mtime if note.is_file() else 0.0
    new, pending = [], []
    for n in _notes_in(place):
        front, _ = split_front(n.read_text(encoding="utf-8", errors="replace"))
        made = n.stat().st_mtime
        try:
            made = datetime.datetime.fromisoformat(str(front.get("created") or "")).timestamp()
        except ValueError:
            pass
        item = {"file": _rel(root, n), "title": n.stem}
        if str(front.get("review") or "").strip().lower() == "pending":
            pending.append(item)
        elif made > wrapped:
            new.append(item)
    return {"since_wrap": new, "awaiting_review": pending}


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
    c.add_argument("--parties", default="", help="comma-separated tags: an index of who it is about, optional")
    c.add_argument("--title", default="", help="what the mail is about (default: its subject)")
    c.add_argument("--date", default="", help="YYYY-MM-DD (default: the mail's own date)")
    c.add_argument("--confirmed", action="store_true",
                   help="the user has answered the question a `Needs your answer first` refusal asked; never pass it unasked")
    r = sub.add_parser("file-reading", help="freeze an item into Knowledge raw/ and write a draft source page")
    r.add_argument("--file", required=True)
    r.add_argument("--title", default="", help="title of the work (default: the subject, or the file name)")
    r.add_argument("--slug", default="", help="the name in Knowledge (default: from the title)")
    r.add_argument("--kind", default="", help="where the original goes, when the wiki's schema.json keeps them by kind")
    t = sub.add_parser("file-to-project", help="move a dropped file into a project's Sources/")
    t.add_argument("--file", required=True)
    t.add_argument("--project", required=True, help="Zones/<Zone>/<Project>")
    t.add_argument("--parties", default="", help="comma-separated tags: whose material this is, an index and optional")
    t.add_argument("--name", default="", help="file name in Sources/ (default: as dropped)")
    t.add_argument("--confirmed", action="store_true",
                   help="the user has answered the question a `Needs your answer first` refusal asked; never pass it unasked")
    t.add_argument("--as-material", action="store_true",
                   help="a mail the user said is material, not a conversation: save the mail itself")
    x = sub.add_parser("extract-attachment", help="save a filed mail's attachment into a project's Sources/")
    x.add_argument("--mail", required=True, help="the filed mail: its slug, or Wikis/Meetings/raw/<slug>.eml")
    x.add_argument("--project", required=True, help="Zones/<Zone>/<Project>")
    x.add_argument("--name", default="", help="the attachment's name, as parse lists it")
    x.add_argument("--index", type=int, default=0, help="the attachment's place in the list, from 1")
    x.add_argument("--save-as", default="", help="file name in Sources/ (default: the attachment's)")
    z = sub.add_parser("move-to-zone", help="move an item from the workspace's Inbox to the zone the user named")
    z.add_argument("--file", required=True)
    z.add_argument("--zone", required=True)
    k = sub.add_parser("skip", help="take an item too thin to keep out of a zone's Inbox, with the reason logged")
    k.add_argument("--file", required=True)
    k.add_argument("--reason", required=True, help="why, in a few words: thin, a promotion, a duplicate")
    n = sub.add_parser("file-note", help="file a note to yourself under the thread it names")
    n.add_argument("--file", required=True)
    n.add_argument("--destination", default="", help="where it goes, as you would say it: \"Acme, pricing\" (default: the note's own)")
    n.add_argument("--title", default="", help="the note's title (default: its first words)")
    q = sub.add_parser("process-notes", help="file the notes waiting in the inboxes and update a thread when one warrants it")
    q.add_argument("--tier", default="sonnet", choices=("haiku", "sonnet", "opus"))
    q.add_argument("--state", default="", help="the durable record (default: notes-state.json in the jobs folder)")
    q.add_argument("--dry-run", action="store_true", help="count what is waiting; write and call nothing")
    q.add_argument("--no-assistant", action="store_true", help="file every resolved note for review, with no assistant")
    w = sub.add_parser("notes", help="the notes since a thread's last wrap, and those waiting for review")
    w.add_argument("--project", required=True, help="Zones/<Zone>/<Project>")
    w.add_argument("--thread", default="", help="a thread of it; leave out for a one-thread project")
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
                print("\t".join((i["kind"], i["zone"], i["file"], i["date"], i["from"], i["subject"]
                                 + (" (says it is a note; no channel recorded it)" if i.get("claim") else ""))).rstrip("\t"))
        elif args.command == "parse":
            print(json.dumps(parse(root, Path(args.file)), indent=2))
        elif args.command == "file-conversation":
            slug, dest, page = file_conversation(root, Path(args.file), _tags(args.parties), args.title, args.date,
                                                 args.today, args.confirmed)
            print("%s\t%s\t%s" % (slug, rel(dest), rel(page)))
        elif args.command == "file-reading":
            slug, dest, page = file_reading(root, Path(args.file), args.title, args.slug, args.today, args.kind)
            print("%s\t%s\t%s" % (slug, rel(dest), rel(page)))
        elif args.command == "file-to-project":
            print(rel(file_to_project(root, Path(args.file), args.project, _tags(args.parties), args.name,
                                      args.as_material, args.confirmed)))
        elif args.command == "extract-attachment":
            how, dest = extract_attachment(root, args.mail, args.project, args.name, args.index, args.save_as)
            print("%s\t%s" % (how, rel(dest)))
        elif args.command == "move-to-zone":
            print(rel(move_to_zone(root, Path(args.file), args.zone)))
        elif args.command == "skip":
            print(skip(root, Path(args.file), args.reason, args.today))
        elif args.command == "file-note":
            done, place = file_note(root, Path(args.file), args.destination, args.title, args.today)
            print("%s\t%s\t%d" % (rel(done["note"]), place["said"], len(done["todo"])))
        elif args.command == "process-notes":
            import process_notes
            if args.state and not process_notes.state_in_jobs(args.state):
                print("--state must be a notes-state file in the jobs folder (%s): it is written whole, so it may not name "
                      "any other file." % process_notes.jobs_dir(), file=sys.stderr)
                return 1
            res = process_notes.run(root, None if (args.dry_run or args.no_assistant) else process_notes.agent_assessor(root, args.tier),
                                    args.state or None, args.today, args.dry_run)
            print(json.dumps(res, sort_keys=True))
            return 1 if res["failed"] else 0
        elif args.command == "notes":
            print(json.dumps(notes_since(root, args.project, args.thread or None), indent=2))
        elif args.command == "learn":
            print("%s\t%s\t%s" % (learn(root, args.domain, args.party), args.domain.strip().lower(), strip_tag(args.party)))
    except Refusal as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
