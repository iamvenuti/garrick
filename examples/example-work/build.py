#!/usr/bin/env python3
"""Build the worked example: Robin Hale's ordinary work at Quillfield Furniture.

    python3 examples/example-work/build.py --target DIR     a new workspace with the example in it
    python3 examples/example-work/build.py --add WORKSPACE  the example, added to a workspace you have

Either way the example is a zone of its own, Example, with its own repository:
five pieces of work, each a project with one thread, a to-do list, and one
question waiting in Needs you. Its files sit in a shared drive, `Quillfield
Shared/`, in the workspace's top folder: outside every zone and wiki, never
committed, and read, never written. Its party and people go into
System/context.md, marked for the Example zone. `System/tools/example.py
archive` puts all of it away and `restore` brings it back.

Dates are relative to the day it is built, so "yesterday" is true on first
open: Robin's last session is the previous working day, and the two calls
were two working days and a week before it. The zone's history is a month of
dated commits leading up to that day.

Standard library only. `install.py --example` calls `add()` after a fresh
install. Refuses a target that is not empty, and a workspace that already has
an Example zone, a drive by that name, or an example put away.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONTENT = HERE / "content"
DRIVE = HERE / "drive"
CONFIG = HERE / "config.json"
EXAMPLE = HERE / "example.json"
INSTALL = REPO / "install.py"

ZONE = "Example"
MANIFEST = ".example.json"   # garrick_lib.EXAMPLE_MANIFEST, which System/tools/example.py reads
# Files a download leaves twice: the second is the same bytes under the name a browser gives it.
DUPLICATES = {"Marketing/Kestle chair launch/Dealer one-pager Final_v3.docx":
              "Marketing/Kestle chair launch/Dealer one-pager Final_v3 (1).docx"}


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------- dates

DAY = datetime.timedelta(days=1)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def weekday_back(d):
    """The day itself, or the Friday before it when it falls on a weekend."""
    while d.weekday() >= 5:
        d -= DAY
    return d


def working_days_before(d, n=1):
    for _ in range(n):
        d = weekday_back(d - DAY)
    return d


def next_weekday(d, weekday):
    """The first `weekday` (0 is Monday) on or after `d`."""
    return d + datetime.timedelta(days=(weekday - d.weekday()) % 7)


def month_end(d):
    first_next = (d.replace(day=28) + 4 * DAY).replace(day=1)
    return first_next - DAY


def nth(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def dates(today):
    """Every date the story uses, from the day it is built.

    Robin's last session is the previous working day; the call with Carla two
    working days before it; the pitch prep with Leo a week before it. The five
    pieces of work were last touched in that order, most recent first, and
    the Spring trade show three weeks ago."""
    last = working_days_before(today)
    call = working_days_before(last, 2)
    prep = last - 7 * DAY
    dealer = weekday_back(last - 8 * DAY)
    spring = weekday_back(today - 21 * DAY)
    arc_start = weekday_back(today - 26 * DAY)
    tom = weekday_back(call + 12 * DAY)
    end = month_end(tom)
    robin = end if (end - tom).days >= 4 else month_end(tom + 8 * DAY)
    close = weekday_back(today + 24 * DAY)
    out = {
        "today": today, "last": last, "call": call, "prep": prep, "dealer": dealer, "spring": spring,
        "zone_start": weekday_back(today - 40 * DAY),
        "spring_start": weekday_back(spring - 12 * DAY),
        "arc_start": arc_start,
        "photos": weekday_back(arc_start + 4 * DAY),
        "onepager": weekday_back(arc_start + 8 * DAY),
        "dealer_start": weekday_back(dealer - 6 * DAY),
        "west_start": weekday_back(prep - 4 * DAY),
        "larch_start": working_days_before(call),
        "order": weekday_back(today - 45 * DAY),
        "ship": weekday_back(last + 21 * DAY),
        "email_due": next_weekday(today, 4),
        "schedule_due": next_weekday(today, 3),
        "close": close,
        "deck_due": close - 7 * DAY,
        "nadia_by": next_weekday(today + 3 * DAY, 4),
        "tom": tom,
        "robin": robin,
        "conference": weekday_back(tom + 3 * DAY),
        "long_ago": weekday_back(today - 330 * DAY),
        "older": weekday_back(today - 420 * DAY),
    }
    jan = datetime.date(today.year, 1, 12)
    out["list_start"] = jan if jan < out["dealer_start"] else out["dealer_start"] - 30 * DAY
    year = today.year
    while (datetime.date(year, 3, 10) - today).days < 90:   # the next March far enough off to be quiet
        year += 1
    out["show"] = datetime.date(year, 3, 10)
    return out


def fields(d):
    """What `{name}` stands for in content/ and drive/: each date in the forms
    the notes use, and the few phrases that depend on them."""
    out = {}
    for key, day in d.items():
        out[key] = day.isoformat()
        out[key + "_long"] = "%d %s %d" % (day.day, MONTHS[day.month - 1], day.year)
        out[key + "_short"] = "%s %d %s" % (WEEKDAYS[day.weekday()], day.day, MONTHS[day.month - 1])
        out[key + "_dm"] = "%d %s" % (day.day, MONTHS[day.month - 1])
        out[key + "_day"] = WEEKDAYS[day.weekday()]
        out[key + "_yymmdd"] = day.strftime("%y%m%d")
        out[key + "_nth"] = "the " + nth(day.day)
    today = d["today"]
    out.update({"year": str(today.year), "next_year": str(today.year + 1), "last_year": str(today.year - 1)})
    out["tom_label"] = "The " + nth(d["tom"].day)
    same_month = (d["robin"].year, d["robin"].month) == (d["call"].year, d["call"].month)
    out["robin_phrase"] = "the end of the month" if same_month else "the end of next month"
    out["robin_label"] = out["robin_phrase"][4:5].upper() + out["robin_phrase"][5:]
    out["robin_said_cap"] = "T" + out["robin_phrase"][1:]
    show = d["show"]
    out["show_year"] = str(show.year)
    out["show_dates"] = "%d to %d %s %d" % (show.day, show.day + 2, MONTHS[show.month - 1], show.year)
    out["pack_month"] = MONTHS[(show.month - 3) % 12]
    return out


FIELD_RE = re.compile(r"\{([a-z_]+)\}")


def fill(text, values, where):
    def one(m):
        if m.group(1) not in values:
            raise BuildError("%s uses {%s}, which the build does not fill" % (where, m.group(1)))
        return values[m.group(1)]
    return FIELD_RE.sub(one, text)


# --------------------------------------------------------------------------- the drive's files


def docx(text, when):
    """A Word document of the text: `# ` and `## ` lines as headings, the rest
    as paragraphs. The smallest file Word, Pages and textutil all open."""
    paras = []
    for line in text.splitlines():
        if not line.strip():
            continue
        size = 32 if line.startswith("# ") else 26 if line.startswith("## ") else None
        words = escape(line.lstrip("# ") if size else line)
        props = '<w:rPr><w:b/><w:sz w:val="%d"/></w:rPr>' % size if size else ""
        paras.append('<w:p><w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (props, words))
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    parts = {
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": head + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paras) + "<w:sectPr/></w:body></w:document>",
    }
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in parts.items():
            info = zipfile.ZipInfo(name, date_time=(when.year, when.month, when.day, 9, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, body.encode("utf-8"))
    return buf.getvalue()


def pdf(text):
    """A one-page PDF of the text, in Helvetica: the first line as a title."""
    def esc(s):
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines = text.splitlines()
    ops = ["BT", "/F1 16 Tf", "56 780 Td", "(%s) Tj" % esc(lines[0] if lines else ""), "/F1 11 Tf", "15 TL", "T*"]
    ops += ["(%s) '" % esc(line) for line in lines[1:]]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def png(label):
    """A small picture standing in for a photograph: a gradient in a colour
    taken from its label, with the label as its description."""
    seed = hashlib.sha256(label.encode("utf-8")).digest()
    width, height = 160, 106
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            shade = 0.55 + 0.45 * (1 - y / height) * (0.6 + 0.4 * x / width)
            rows += bytes(min(255, int(c * shade) + 30) for c in seed[:3])

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"Description\0" + label.strip().encode("latin-1", "replace"))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


# When each file in the drive was last saved: the first prefix that matches wins.
SAVED = (
    ("Marketing/Kestle chair launch/Launch email draft.txt", "last", 17, 35),
    ("Marketing/Kestle chair launch/Kestle chair launch brief", "arc_start", 11, 20),
    ("Marketing/Kestle chair launch/Dealer one-pager Final_v3 (1)", "onepager", 16, 40),
    ("Marketing/Kestle chair launch/Dealer one-pager", "onepager", 15, 55),
    ("Marketing/Kestle chair launch/Photo selects/", "photos", 14, 10),
    ("Marketing/Spring trade show/Booking confirmation", "spring", 14, 30),
    ("Marketing/Spring trade show/", "long_ago", 12, 0),
    ("Marketing/Brand assets/", "older", 10, 0),
    ("Sales/Ellisford University tender/Tender documents", "west_start", 10, 15),
    ("Sales/Ellisford University tender/University case study", "long_ago", 9, 30),
    ("Sales/Ellisford University tender/", "prep", 15, 20),
    ("Customer service/Brannock delivery problem/Original order", "order", 9, 45),
    ("Customer service/Brannock delivery problem/Call with", "call", 16, 30),
    ("Customer service/Brannock delivery problem/", "larch_start", 11, 0),
    ("Finance/Dealer price list/Dealer price list {year}", "list_start", 10, 0),
    ("Finance/Dealer price list/Dealer price list {next_year} draft", "dealer", 16, 20),
    ("Finance/Dealer price list/", "dealer_start", 10, 40),
    ("Misc/", "long_ago", 13, 5),
    ("Old - do not use/", "older", 9, 0),
)


def lay_drive(drive, values, d):
    """Write the drive: every file of drive/, with its dates filled in, a
    `.docx.txt`, `.pdf.txt` or `.png.txt` made into that kind of file, each
    file dated the day it was last saved. Returns the paths written."""
    saved = [(fill(prefix, values, "SAVED"), key, h, m) for prefix, key, h, m in SAVED]
    written = []
    sources = sorted(p for p in (DRIVE / "Quillfield Shared").rglob("*") if p.is_file() and p.name != ".DS_Store")
    for src in sources:
        rel = fill(src.relative_to(DRIVE / "Quillfield Shared").as_posix(), values, "a drive path")
        text = fill(src.read_text(encoding="utf-8"), values, rel)
        hit = next(((key, h, m) for prefix, key, h, m in saved if rel.startswith(prefix)), ("zone_start", 9, 0))
        when = d[hit[0]]
        if rel.endswith(".docx.txt"):
            rel, data = rel[:-4], docx(text, when)
        elif rel.endswith(".pdf.txt"):
            rel, data = rel[:-4], pdf(text)
        elif rel.endswith(".png.txt"):
            rel, data = rel[:-4], png(text)
        else:
            data = text.encode("utf-8")
        copies = [rel] + ([DUPLICATES[rel]] if rel in DUPLICATES else [])
        for name in copies:
            hit = next(((key, h, m) for prefix, key, h, m in saved if name.startswith(prefix)), hit)
            stamp = datetime.datetime(d[hit[0]].year, d[hit[0]].month, d[hit[0]].day, hit[1], hit[2]).timestamp()
            path = drive / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            os.utime(str(path), (stamp, stamp))
            written.append(path)
    return written


# --------------------------------------------------------------------------- the zone's history


def project(name, thread, *todo_keys):
    return ("project", name, thread, todo_keys)


def wrap(name, done=(), todo=()):
    return ("wrap", name, tuple(done), tuple(todo))


def ticked(*keys):
    return ("done", keys)


# (the day, the time, what it does, the commit message). A project is made by the
# workspace's own scaffold script; a wrap writes its notes from content/, as they
# stand at the end; to-do lines are added and ticked as content/'s Todo.md has them.
PLAN = (
    ("spring_start", "10:00", project("Spring trade show", "Stand", "Book the stand"),
     "New project Spring trade show (quillfield), first thread Stand"),
    ("arc_start", "09:30", project("Kestle chair launch", "Launch campaign", "Dealer one-pager"),
     "New project Kestle chair launch (quillfield), first thread Launch campaign"),
    ("dealer_start", "11:00", project("Dealer price list {next_year}", "New prices", "Draft {next_year} list"),
     "New project Dealer price list {next_year} (quillfield), first thread New prices"),
    ("spring", "15:00", wrap("Spring trade show", done=["Book the stand"]),
     "Spring trade show, Stand: stand booked; nothing more until the exhibitor pack"),
    ("onepager", "16:00", ticked("Dealer one-pager"),
     "Kestle chair launch, Launch campaign: dealer one-pager to Leo"),
    ("west_start", "10:30", project("Ellisford University tender", "Pitch"),
     "New project Ellisford University tender (quillfield), first thread Pitch"),
    ("dealer", "16:30", wrap("Dealer price list {next_year}", done=["Draft {next_year} list"]),
     "Dealer price list {next_year}, New prices: draft list to Nadia; waiting on her margins"),
    ("prep", "15:30", wrap("Ellisford University tender", todo=["Pitch deck to Leo"]),
     "Ellisford University tender, Pitch: prep with Leo; the sustainability page is Robin's"),
    ("larch_start", "11:30", project("Brannock delivery problem", "Replacement desks"),
     "New project Brannock delivery problem (quillfield), first thread Replacement desks"),
    ("call", "16:45", wrap("Brannock delivery problem", todo=["Replacement schedule", "Damage photos"]),
     "Brannock delivery problem, Replacement desks: call with Carla; which date was promised is in Needs you"),
    ("last", "17:40", wrap("Kestle chair launch", todo=["Launch email draft"]),
     "Kestle chair launch, Launch campaign: launch email half written; stops before pricing"),
)


class TodoList:
    """Replays the zone's Todo.md: a line appears when the plan adds it and
    moves to Done when the plan ticks it. With every line added and ticked,
    the result is content/'s file exactly."""

    def __init__(self, text):
        lines = text.rstrip("\n").splitlines()
        i_inbox, i_done = lines.index("## Inbox"), lines.index("## Done")
        self.head = lines[:i_inbox]
        self.open_items = [l for l in lines[i_inbox + 1:i_done] if l.startswith("- [")]
        self.done_items = [l for l in lines[i_done + 1:] if l.startswith("- [")]
        self.shown, self.ticked = set(), set()

    def _find(self, key):
        hits = [l for l in self.open_items + self.done_items if key in l]
        if len(hits) != 1:
            raise BuildError("to-do key %r matches %d lines" % (key, len(hits)))
        return hits[0]

    def show(self, key):
        self.shown.add(self._find(key))

    def tick(self, key):
        line = self._find(key)
        if line not in self.done_items:
            raise BuildError("%r is not ticked in content/" % key)
        self.ticked.add(line)

    def render(self):
        inbox = [l for l in self.open_items if l in self.shown]
        inbox += [re.sub(r" ✅ \d{4}-\d{2}-\d{2}$", "", "- [ ]" + l[5:])
                  for l in self.done_items if l in self.shown and l not in self.ticked]
        done = [l for l in self.done_items if l in self.ticked]
        out = self.head + ["## Inbox", ""] + inbox + ([""] if inbox else []) + ["## Done", ""] + done
        return "\n".join(out).rstrip("\n") + "\n"


def offset():
    return datetime.datetime.now().astimezone().strftime("%z")


def stamp(day, hhmm):
    z = offset()
    return "%sT%s:00%s:%s" % (day.isoformat(), hhmm, z[:3], z[3:])


def run(args, cwd, when=None, what="a command"):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    r = subprocess.run([str(a) for a in args], cwd=str(cwd), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError("%s failed: %s" % (what, (r.stderr.strip() or r.stdout.strip())))
    return r.stdout


def scaffold(root, today, when, *args):
    return run([sys.executable, root / "System" / "tools" / "scaffold.py", "--root", root, "--today", today]
               + list(args), root, when, "scaffold.py " + args[0])


def content_files(project_name, values):
    """(content path, workspace path) of every file content/ holds for a project."""
    out = []
    zone_src = CONTENT / "Zones" / ZONE
    for src in sorted(zone_src.rglob("*")):
        if not src.is_file() or src.name == ".DS_Store":
            continue
        rel = fill(src.relative_to(zone_src).as_posix(), values, "a content path")
        if rel.split("/")[0] == project_name:
            out.append((src, rel))
    return out


# --------------------------------------------------------------------------- context.md


def table_rows(lines, heading):
    start = next((i for i, l in enumerate(lines) if l.strip().lower() == "## " + heading.lower()), None)
    if start is None:
        raise BuildError("System/context.md has no `## %s` table." % heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].lstrip().startswith("|")]
    if len(rows) < 2:
        raise BuildError("System/context.md's `## %s` section has no table." % heading)
    header = [c.strip().lower() for c in lines[rows[0]].strip().strip("|").split("|")]
    return header, rows


def add_rows(root, data):
    """The party and its people, at the end of their tables, in the columns
    each table has. Garrick writes them, so they carry no Learned cell."""
    path = root / "System" / "context.md"
    lines = path.read_text(encoding="utf-8").split("\n")
    party = data["party"]
    wanted = {"Parties": [{"party": party["name"], "what it is": party["what"], "zone": data["zone"],
                           "tag": "`%s`" % party["tag"], "domains": ", ".join(party.get("domains", []))}],
              "People": [{"name": p["name"], "party": "`%s`" % party["tag"], "role": p["role"]}
                         for p in data["people"]]}
    for heading, rows in wanted.items():
        header, at = table_rows(lines, heading)
        new = ["| " + " | ".join(row.get(col, "") for col in header) + " |" for row in rows]
        lines[at[-1] + 1:at[-1] + 1] = new
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- adding it


def load_install():
    spec = importlib.util.spec_from_file_location("garrick_install_for_example", INSTALL)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(REPO))
    return module


def git_quiet(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def refuse_unless_ready(root, data):
    if not (root / "AGENTS.md").is_file() or not (root / "System" / "context.md").is_file():
        raise BuildError("%s does not look like a Garrick workspace." % root)
    if (root / "Zones" / data["zone"]).exists():
        raise BuildError("%s already has a zone called %s, so the example cannot be added there."
                         % (root, data["zone"]))
    if (root / data["drive"]).exists():
        raise BuildError("%s already has a folder called %s, so the example's drive cannot be laid down there."
                         % (root, data["drive"]))
    if (root / ".archive" / data["zone"]).exists():
        raise BuildError("The example was put away earlier. Bring it back instead: "
                         "python3 System/tools/example.py restore")
    if not (root / "System" / "tools" / "example.py").is_file():
        raise BuildError("This workspace has no System/tools/example.py, so the example could not be removed "
                         "again. Update the workspace to this Garrick first: python3 install.py --update")
    if (root / ".git").exists() and git_quiet(root, "check-ignore", "-q", data["drive"] + "/").returncode != 0:
        raise BuildError("The workspace's .gitignore does not keep %s/ out of its history. Update the workspace "
                         "to this Garrick first: python3 install.py --update" % data["drive"])


def add(root, today=None, quiet=False):
    """Add the example to the workspace at `root`: the Example zone with its
    month of history, the drive, and the context rows, committed. Returns
    what to say."""
    root = Path(os.path.abspath(Path(root).expanduser())).resolve()
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    refuse_unless_ready(root, data)
    today = today or datetime.date.today()
    d = dates(today)
    values = fields(d)
    zone_dir = root / "Zones" / data["zone"]
    root_files = ["System/context.md", "System/garrick-version.json", ".claude/settings.json",
                  "System/garrick-settings.json"]
    was_clean = {r: not git_quiet(root, "status", "--porcelain", "--", r).stdout.strip() for r in root_files}

    lay_drive(root / data["drive"], values, d)

    first = stamp(d["zone_start"], "09:00")
    scaffold(root, d["zone_start"].isoformat(), first, "zone", data["zone"], "--holds", data["holds"])
    manifest = {"name": data["name"], "zone": data["zone"], "drive": data["drive"],
                "parties": [data["party"]["tag"]], "added": today.isoformat()}
    (zone_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    run(["git", "add", MANIFEST], zone_dir, first, "staging the manifest")
    run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m",
         "Example: %s, a worked example to try Garrick on" % data["name"]], zone_dir, stamp(d["zone_start"], "09:05"),
        "committing the manifest")
    add_rows(root, data)

    todo = TodoList(fill((CONTENT / "Zones" / ZONE / "Todo.md").read_text(encoding="utf-8"), values, "Todo.md"))
    steps = sorted(PLAN, key=lambda s: (d[s[0]], s[1]))
    for key, hhmm, action, message in steps:
        day, when = d[key].isoformat(), stamp(d[key], hhmm)
        kind = action[0]
        if kind == "project":
            name, thread = fill(action[1], values, "PLAN"), action[2]
            scaffold(root, day, when, "project", "--zone", data["zone"], "--name", name,
                     "--party", data["party"]["tag"], "--thread", thread)
            for k in action[3]:
                todo.show(fill(k, values, "PLAN"))
        elif kind == "wrap":
            name = fill(action[1], values, "PLAN")
            files = content_files(name, values)
            if not files:
                raise BuildError("content/ has nothing for %s" % name)
            for src, rel in files:
                dst = zone_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(fill(src.read_text(encoding="utf-8"), values, rel), encoding="utf-8")
            for k in action[2]:
                todo.tick(fill(k, values, "PLAN"))
            for k in action[3]:
                todo.show(fill(k, values, "PLAN"))
        else:
            for k in action[1]:
                todo.tick(fill(k, values, "PLAN"))
        (zone_dir / "Todo.md").write_text(todo.render(), encoding="utf-8")
        run(["git", "add", "-A"], zone_dir, when, "staging %r" % message)
        run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", fill(message, values, "PLAN")],
            zone_dir, when, "committing %r" % message)

    # Every file content/ holds is now in place, exactly, and the zone is clean.
    for src in sorted(p for p in (CONTENT / "Zones" / ZONE).rglob("*") if p.is_file() and p.name != ".DS_Store"):
        rel = fill(src.relative_to(CONTENT / "Zones" / ZONE).as_posix(), values, "a content path")
        want = fill(src.read_text(encoding="utf-8"), values, rel)
        if (zone_dir / rel).read_text(encoding="utf-8") != want:
            raise BuildError("%s did not end up as content/ has it; check the plan in build.py" % rel)
    left = git_quiet(zone_dir, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if left:
        raise BuildError("The Example zone has changes the plan did not commit: %s" % left)

    # The commands the assistant may run in the new zone, where the workspace allowed Garrick's own.
    install = load_install()
    lib = install.lib()
    ours = root.joinpath(*lib.SETTINGS)
    if lib.ALLOWED_COMMANDS in (json.loads(ours.read_text(encoding="utf-8")) if ours.is_file() else {}):
        files, _, _ = install.allowlist_files(root, install.workspace_zones(root))
        for rel, text in files.items():
            (root / rel).write_text(text, encoding="utf-8")

    said = ["The example is in %s: Robin Hale's work at %s, in the %s zone, with its files in %s/."
            % (root, data["name"], data["zone"], data["drive"]),
            "  Five pieces of work, Kestle chair launch on top; one question in Needs you.",
            "  To remove it: python3 System/tools/example.py archive. To bring it back: restore."]
    changed = [r for r in root_files if git_quiet(root, "status", "--porcelain", "--", r).stdout.strip()]
    if (root / ".git").exists() and changed:
        if all(was_clean[r] for r in changed):
            r = git_quiet(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m",
                          "Example: %s added, in the %s zone" % (data["name"], data["zone"]), "--", *changed)
            if r.returncode != 0:
                said.append("  %s changed but could not be committed: %s" % (" and ".join(changed), r.stderr.strip()))
        else:
            said.append("  %s had changes of yours not yet committed, so the example's rows are left beside them."
                        % " and ".join(r for r in changed if not was_clean[r]))
    if not quiet:
        print("\n".join(said))
    return root


def build(target, today=None):
    """A new workspace with the example in it."""
    target = Path(os.path.abspath(Path(target).expanduser()))
    if target.exists() and [p for p in target.iterdir() if p.name != ".DS_Store"]:
        raise BuildError("%s is not empty. Pick an empty or new folder." % target)
    run([sys.executable, INSTALL, "--config", CONFIG, "--target", target], REPO, None, "install.py")
    return add(target, today)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the worked example: Robin Hale's work at Quillfield Furniture.")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--target", help="an empty or new folder: a new workspace with the example in it")
    where.add_argument("--add", metavar="WORKSPACE", help="a workspace you have: the example added to it")
    ap.add_argument("--today", help="YYYY-MM-DD to build as if on, instead of today")
    args = ap.parse_args(argv)
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else None
        if args.target:
            build(args.target, today)
        else:
            add(args.add, today)
    except (BuildError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
