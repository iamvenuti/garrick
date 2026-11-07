#!/usr/bin/env python3
"""Recall, sessions: plain-text copies of Claude Code and Codex sessions (#341).

    python3 System/tools/recall.py extract [--claude DIR] [--codex DIR]

A harness keeps each session as a JSON-lines transcript and, for Claude Code,
deletes it after `cleanupPeriodDays` (30 by default). This module writes what
was said as one Markdown file per session, `<YYMMDD> - <session id>.md`, into
a gitignored `.sessions/` folder:

- a session opened in a project of a zone goes to `Zones/<Zone>/.sessions/`;
- one opened at the workspace root or in `System/` goes to `System/.sessions/`;
- one whose folder cannot be placed plainly goes nowhere.

The text holds what the user said, what the assistant said, and the commands
the assistant ran, each with its exit status as one short line. It holds no
tool output and nothing loaded into the session from outside it (rules,
context, the memory index). Anything shaped like a key, a token or a password
is masked before the file is written.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import recall  # noqa: E402

MASK = "[masked]"
MAX_TEXT = 20000
MAX_COMMAND = 1500
TITLE_CHARS = 80

# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

_LONG_WORDS = r"(?:api[\s_-]?key|apikey|access[_-]?key|secret[_-]?key|private[_-]?key|secret|token|passwd|password|" \
              r"passphrase|credential[s]?|auth(?:orization)?|bearer|client[_-]?secret)"
_SHORT_WORDS = r"(?:pass|pw|pwd|key|otp)"
# A name that carries a secret word: it may run on either side of a long word
# (MY_TOKEN_2), but a short one (pass, pw, key) stands as a word of its own, or
# between `_`, `.` and `-`, so `keyboard` and `compass` are left alone.
_NAME = r"(?:(?<![\w.-])[\w.-]*?" + _LONG_WORDS + r"[\w.-]{0,128}|(?<![A-Za-z0-9])(?:[A-Za-z0-9]{1,48}[_.-]){0,6}" + \
        _SHORT_WORDS + r"(?:[_.-][A-Za-z0-9]{1,48}){0,6}(?![A-Za-z0-9]))"
_PLAIN_WORDS = r"(?:api[\s_-]?key|apikey|secret|token|password|passwd|passphrase|pass|pwd|pw|key|otp)"
_QUOTED = r"(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"[^\"\n]*\"|'[^'\n]*')"
_COMMANDS = r"(?:mysql\w*|mariadb\w*|sshpass|psql|pg_dump\w*|redis-cli|mongo\w*|docker\s+login|podman\s+login)"
MASKERS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), MASK),
    (re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@"), lambda m: m.group(0).split("://")[0] + "://" + MASK + "@"),
    # Webhook and bot URLs carry the secret in the path.
    (re.compile(r"(?i)hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_-]+"), "hooks.slack.com/" + MASK),
    (re.compile(r"(?i)(discord(?:app)?\.com/api/webhooks/)[A-Za-z0-9/_-]+"), lambda m: m.group(1) + MASK),
    (re.compile(r"(?i)(api\.telegram\.org/(?:file/)?bot)[0-9]+:[A-Za-z0-9_-]+"), lambda m: m.group(1) + MASK),
    (re.compile(r"\b[0-9]{6,}:[A-Za-z0-9_-]{30,}"), MASK),
    # A block scalar: SECRET: | and the indented lines under it.
    (re.compile(r"(?im)^([ \t]*[\w.-]*?" + _LONG_WORDS + r"[\w.-]{0,128}[ \t]*:[ \t]*[|>][+-]?[ \t]*\n)((?:[ \t]+[^\n]*(?:\n|$))+)"),
     lambda m: m.group(1) + "  " + MASK + "\n"),
    # Authorization: Token x / Basic x / Bearer x / anything: the whole value.
    (re.compile(r"(?i)(\bauthorization\b[\"\']?\s*[:=]\s*[\"\']?)([^\r\n\"\']+)"), lambda m: m.group(1) + MASK),
    # Cookie: and Set-Cookie: carry a session; --cookie too.
    (re.compile(r"(?i)(\b(?:set-)?cookie\b[\"\']?\s*[:=]\s*[\"\']?)([^\r\n\"\']+)"), lambda m: m.group(1) + MASK),
    (re.compile(r"(?i)(--cookie(?:-jar)?[=\s]+)(\"[^\"]*\"|'[^']*'|\S+)"), lambda m: m.group(1) + MASK),
    # A secret piped into a command that reads it from standard input.
    (re.compile(r"(?i)(\b(?:echo|printf)\s+(?:-[a-z]+\s+)*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s|]+)(\s*\|[^\n]{0,300}?--password-stdin)"),
     lambda m: m.group(1) + MASK + m.group(3)),
    (re.compile(r"(?i)(--password-stdin[^\n]{0,300}?<<<\s*)(\"[^\"\n]*\"|'[^'\n]*'|\S+)"), lambda m: m.group(1) + MASK),
    # openssl enc -k hunter2, -pass pass:hunter2, -passin pass:hunter2.
    (re.compile(r"(?i)(?<![\w-])(openssl\b[^\n|;&]{0,300}?\s-k\s+)(\"[^\"]*\"|'[^']*'|\S+)"), lambda m: m.group(1) + MASK),
    (re.compile(r"(?i)(-pass(?:in|out)?[=\s]+pass:)(\"[^\"]*\"|'[^']*'|\S+)"), lambda m: m.group(1) + MASK),
    # aws configure set aws_secret_access_key VALUE: a name that ends in one of these, then its value.
    (re.compile(r"(?i)\b(\w*(?:secret_access_key|access_key_id|session_token|_token|_secret)[ \t]+)(?!\[masked\])"
                r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;\"')\]}]+)"), lambda m: m.group(1) + MASK),
    (re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), lambda m: m.group(1) + " " + MASK),
    (re.compile(r"(?i)\b(Token)\s+(?=[A-Za-z0-9._~+/=-]*[0-9])[A-Za-z0-9._~+/=-]{8,}"), lambda m: m.group(1) + " " + MASK),
    (re.compile(r"(?i)(--?[a-z-]{0,64}(?:password|passwd|pass|token|secret|api-?key|apikey)[a-z-]{0,64})([=\s]+)(\"[^\"]*\"|'[^']*'|\S+)"),
     lambda m: m.group(1) + m.group(2) + MASK),
    # Command lines that take a password: mysql -phunter2, mysql -p hunter2, sshpass -p hunter2, curl -u user:pass.
    (re.compile(r"(?<![\w-])(" + _COMMANDS + r")(\s(?:[^\n|;&]*?\s)?)-p\s*(?=\S)\S+"),
     lambda m: m.group(1) + m.group(2) + "-p " + MASK),
    (re.compile(r"(?<!\S)(-u|--user)([=\s]+)([^\s:]+):\S+"), lambda m: m.group(1) + m.group(2) + m.group(3) + ":" + MASK),
    # NAME = "quoted", NAME: "quoted", """triple quoted""".
    (re.compile(r"(?i)(" + _NAME + r"[\"\']?\s*[:=]\s*)" + _QUOTED), lambda m: m.group(1) + MASK),
    # NAME: a value that may be several words: to the end of the line.
    (re.compile(r"(?i)(" + _NAME + r"[\"\']?[ \t]*:)(?![ \t]*\[masked\])[ \t]*[^\n]+"), lambda m: m.group(1) + " " + MASK),
    # NAME=value
    (re.compile(r"(?i)(" + _NAME + r"[\"\']?\s*=)(?!\s*\[masked\])\s*[^\s,;\"')\]}]+"), lambda m: m.group(1) + MASK),
    # the password is hunter2 / the api key was ...: to the end of the line.
    (re.compile(r"(?i)(\b" + _PLAIN_WORDS + r"[ \t]+(?:is|was|are|=))(?![ \t]*:?[ \t]*\[masked\])[ \t]+:?[ \t]*[^\n]+"),
     lambda m: m.group(1) + " " + MASK),
    # PASSWORD hunter2 / pass hunter2: the next word, whatever it is.
    (re.compile(r"(?i)(\b" + _PLAIN_WORDS + r"[ \t]+)(?!\[masked\]|(?:is|was|are)\b)[^\s,;\"')\]}]+"), lambda m: m.group(1) + MASK),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}"), MASK),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), MASK),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), MASK),
]
# A long unbroken run of letters and digits is a key whatever it is called. Hex
# digests and long mixed strings alike: a git hash of 40 characters goes too, since
# some tokens are 40 hex characters.
LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+=-])[A-Za-z0-9_+=-]{32,}(?![A-Za-z0-9_+=-])")

# A base64-looking key with slashes (an AWS secret key is 40 of these): it may
# not start at or follow a slash, so a path is not one, and it needs digits and
# both cases of letters.
SLASH_TOKEN = re.compile(r"(?<![A-Za-z0-9_+/=.-])[A-Za-z0-9+][A-Za-z0-9+/]{39,}={0,2}(?![A-Za-z0-9_+/=-])")


def mask(text: str) -> str:
    """`text` with anything shaped like a key, a token or a password replaced
    by [masked]."""
    for pattern, repl in MASKERS:
        text = pattern.sub(repl, text)

    def long_run(m: "re.Match") -> str:
        run = m.group(0)
        if len(set(run)) < 6:                      # "-----", "=======", "aaaa..."
            return run
        if re.fullmatch(r"[A-Za-z]+(?:[_-][A-Za-z]+)+", run):    # a long-kebab-case-name
            return run
        return MASK
    def slash_run(m: "re.Match") -> str:
        run = m.group(0)
        if "/" in run and re.search(r"[0-9]", run) and re.search(r"[a-z]", run) and re.search(r"[A-Z]", run):
            return MASK
        return run
    return SLASH_TOKEN.sub(slash_run, LONG_TOKEN.sub(long_run, text))


CUT_MARGIN = 4096


def mask_to(text: str, limit: int) -> str:
    """`mask(text)` cut to `limit` characters, without masking what would be
    thrown away. The text is cut a little past the limit, masked, and cut
    again; when the first cut fell inside the text, the word it may have split
    is dropped too, so that half a secret never stays."""
    if len(text) <= limit + CUT_MARGIN:
        return mask(text)[:limit]
    out = mask(text[:limit + CUT_MARGIN])
    return re.sub(r"[\w+=./~:@-]*\Z", "", out[:limit + 1])[:limit]


# ---------------------------------------------------------------------------
# What a session holds
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Session:
    id: str
    harness: str
    started: Optional[datetime.datetime] = None
    cwds: List[str] = dataclasses.field(default_factory=list)
    turns: List[Tuple[str, str, Optional[str]]] = dataclasses.field(default_factory=list)   # (kind, text, exit)


REMINDER = re.compile(r"<(system-reminder|local-command-caveat|local-command-stdout|command-stdout|"
                      r"user-prompt-submit-hook|environment_context|user_instructions|permissions instructions|"
                      r"INSTRUCTIONS|collaboration_mode|recent_conversation)>.*?</\1>", re.S)
INJECTED_START = ("# AGENTS.md instructions", "<environment_context>", "<user_instructions>", "<INSTRUCTIONS>",
                  "Caveat: The messages below were generated by the user while running local commands")


def clean_user(text: str) -> str:
    text = REMINDER.sub("", text).strip()
    return "" if text.startswith(INJECTED_START) else text


def add_turn(session: Session, kind: str, text: str) -> None:
    text = text.strip()
    if text:
        session.turns.append((kind, text, None))


def parse_time(value) -> Optional[datetime.datetime]:
    """An ISO time. Python 3.9 reads fractions of three or six digits only, so
    any other length is made six first."""
    text = str(value).strip().replace("Z", "+00:00")
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def records(path: Path) -> Iterable[dict]:
    try:
        with open(str(path), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
    except OSError:
        return


def block_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def exit_of(text: str, error: bool) -> str:
    m = re.search(r"(?i)\bexit(?:ed with)?(?: code)?[:=\s]+(-?\d+)", text) or re.search(r'"exit_code"\s*:\s*(-?\d+)', text) \
        or re.search(r"(?i)exited with code (-?\d+)", text)
    if m:
        return "exit " + m.group(1)
    return "exit 1" if error else "exit 0"


def parse_claude(path: Path) -> Session:
    s = Session(path.stem, "claude-code")
    pending: Dict[str, int] = {}
    for d in records(path):
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        if d.get("cwd") and d["cwd"] not in s.cwds:
            s.cwds.append(str(d["cwd"]))
        if d.get("sessionId"):
            s.id = str(d["sessionId"])
        if s.started is None and d.get("timestamp"):
            s.started = parse_time(d["timestamp"])
        message = d.get("message")
        if d.get("type") not in ("user", "assistant") or not isinstance(message, dict):
            continue
        content = message.get("content")
        if d["type"] == "user":
            if isinstance(content, str):
                add_turn(s, "user", clean_user(content))
                continue
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    add_turn(s, "user", clean_user(str(b.get("text") or "")))
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    k = pending.pop(b["tool_use_id"])
                    kind, text, _ = s.turns[k]
                    s.turns[k] = (kind, text, exit_of(block_text(b.get("content")), bool(b.get("is_error"))))
        else:
            if isinstance(content, str):
                add_turn(s, "assistant", content)
                continue
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    add_turn(s, "assistant", str(b.get("text") or ""))
                elif b.get("type") == "tool_use" and str(b.get("name")) == "Bash":
                    command = str((b.get("input") or {}).get("command") or "").strip()
                    if command:
                        s.turns.append(("command", command, None))
                        pending[str(b.get("id"))] = len(s.turns) - 1
    return s


def parse_codex(path: Path) -> Session:
    s = Session(path.stem, "codex")
    pending: Dict[str, int] = {}
    for d in records(path):
        p = d.get("payload")
        if not isinstance(p, dict):
            continue
        if s.started is None and d.get("timestamp"):
            s.started = parse_time(d["timestamp"])
        if d.get("type") == "session_meta":
            s.id = str(p.get("id") or p.get("session_id") or s.id)
        if d.get("type") in ("session_meta", "turn_context") and p.get("cwd") and str(p["cwd"]) not in s.cwds:
            s.cwds.append(str(p["cwd"]))
        if d.get("type") != "response_item":
            continue
        kind = p.get("type")
        if kind == "message" and p.get("role") in ("user", "assistant"):
            text = block_text(p.get("content"))
            if p["role"] == "user":
                add_turn(s, "user", clean_user(text))
            else:
                add_turn(s, "assistant", text)
        elif kind == "function_call":
            try:
                args = json.loads(p.get("arguments") or "{}")
            except ValueError:
                args = {}
            command = args.get("command") if isinstance(args, dict) else None
            command = command if command else (args.get("cmd") if isinstance(args, dict) else None)
            if isinstance(command, list):
                command = " ".join(str(c) for c in command)
            if command:
                s.turns.append(("command", str(command).strip(), None))
                pending[str(p.get("call_id"))] = len(s.turns) - 1
        elif kind == "function_call_output" and str(p.get("call_id")) in pending:
            k = pending.pop(str(p["call_id"]))
            out = p.get("output")
            text = block_text(out) if not isinstance(out, str) else out
            found = re.search(r"(?i)exit code[:=\s]+(-?\d+)|exited with code (-?\d+)|\"exit_code\"\s*:\s*(-?\d+)", text)
            kind_, cmd, _ = s.turns[k]
            if found:
                s.turns[k] = (kind_, cmd, "exit " + next(g for g in found.groups() if g is not None))
    return s


# ---------------------------------------------------------------------------
# Where a session belongs
# ---------------------------------------------------------------------------

def destination(root: Path, s: Session) -> Optional[Tuple[Path, List[str]]]:
    """(the folder that holds the `.sessions/` it goes in, the project folders
    it worked in, from the workspace's top), or None. The zone is decided by
    the folders the session was opened in, resolved against the workspace; when
    one cannot be placed, or they point at two zones, the answer is None."""
    base = root.resolve()
    places = set()
    projects: List[str] = []
    zone_level = False
    if not s.cwds:
        return None
    for cwd in s.cwds:
        p = Path(cwd)
        if not p.is_absolute():
            return None
        place = recall.locate(base, p)
        if place is None:
            return None
        places.add(place.zone)
        if place.zone and not place.project:
            zone_level = True
        if place.zone and place.project:
            rel = "Zones/%s/%s" % (place.zone, place.project)
            if rel not in projects:
                projects.append(rel)
    if len(places) != 1:
        return None
    found = mentioned(base, s)
    if found is None:
        return None                                 # a workspace path that names no place: the session is dropped
    for rel in found:
        if rel not in projects:
            projects.append(rel)
    zone = places.pop()
    if zone:
        folder = base / "Zones" / zone
        if not folder.is_dir() or folder.is_symlink():
            return None
        names = [z for z in recall.zone_names(base)]
        if zone not in names:
            return None
        # A session that was open at the zone's top at any point is the zone's, not a project's:
        # it is labelled with no project, and only zone-level searches read it.
        return folder, [] if zone_level else projects
    folder = base / "System"
    return (folder, []) if folder.is_dir() and not folder.is_symlink() else None


PATH_TOKEN = re.compile(r"Zones/([^/\s\"'`;|&()<>{}$*\\]+)/([^/\s\"'`;|&()<>{}$*\\]+)")


def project_folders(base: Path) -> List[Tuple[str, str]]:
    out = []
    for zone in recall.zone_names(base):
        try:
            for p in sorted((base / "Zones" / zone).iterdir()):
                if p.is_dir() and not p.name.startswith(".") and not p.is_symlink() and p.name != "Inbox":
                    out.append((zone, p.name))
        except OSError:
            pass
    return out


def mentioned(base: Path, s: Session) -> Optional[List[str]]:
    """Every project a session's text points at by path: `Zones/<zone>/<project>`
    in a command or a turn, or `<project>/` as a path component (a relative path
    such as `../Other/Threads/T/x.md` read without changing folder). Each is
    added to the session's projects, so a transcript that quotes another
    project's file is labelled with it as well. A `Zones/<zone>/<name>` path in a
    zone of the workspace that is neither a folder nor a file there cannot be
    placed, and the session is dropped (None)."""
    folders = project_folders(base)
    zones = {z for z, _ in folders} | set(recall.zone_names(base))
    found: List[str] = []
    for _kind, text, _status in s.turns:
        rest = text
        for zone, name in sorted(folders, key=lambda f: -len(f[1])):
            literal = "Zones/%s/%s" % (zone, name)
            if literal in rest:
                if literal not in found:
                    found.append(literal)
                rest = rest.replace(literal, " ")
            if re.search(r"(?:^|[/\s\"'`=:(])%s/" % re.escape(name), text):
                if literal not in found:
                    found.append(literal)
        for zone, name in PATH_TOKEN.findall(rest):
            if zone not in zones or zone.startswith("<"):
                continue
            target = base / "Zones" / zone / name
            if target.is_dir():
                literal = "Zones/%s/%s" % (zone, name)
                if literal not in found:
                    found.append(literal)
            elif not target.exists():
                return None
    return found


def header_value(value) -> str:
    """One line, no control characters, nothing that could close or forge a
    frontmatter field: whatever a transcript supplies goes through here."""
    text = "".join(" " if (c.isspace() or ord(c) < 32 or ord(c) == 127) else c for c in str(value))
    return " ".join(text.replace("\\", "/").replace('"', "'").split())


def clean_name(value) -> str:
    """A folder name for the header: control characters out, the rest as it is
    (the header holds it as JSON, so `#`, `:` and quotes are safe)."""
    return "".join(" " if (c.isspace() or ord(c) < 32 or ord(c) == 127) else c for c in str(value)).strip()


def render(s: Session, projects: List[str], size: int, mtime: int) -> str:
    first = next((t for k, t, _ in s.turns if k == "user"), "")
    title = header_value(mask_to(first, TITLE_CHARS * 8))[:TITLE_CHARS]
    date = (s.started or datetime.datetime.now()).date().isoformat()
    head = ["---", 'title: "%s"' % title, "type: session", "harness: %s" % header_value(s.harness),
            "session: %s" % safe_id(s.id), "format: 2",
            "date: %s" % date]
    if projects:
        head.append("project: %s" % json.dumps([clean_name(p) for p in projects]))
    head += ["source_size: %d" % size, "source_mtime: %d" % mtime, "---", ""]
    out = []
    for kind, text, status in s.turns:
        text = mask_to(text, MAX_COMMAND + 1 if kind == "command" else MAX_TEXT)
        if kind == "command":
            text = text if len(text) <= MAX_COMMAND else text[:MAX_COMMAND] + " ..."
            out += ["### Command", "", "```sh", text.replace("```", "'''"), "```"]
            if status:
                out.append(status)
            out.append("")
        else:
            out += ["## " + ("User" if kind == "user" else "Assistant"), "", text, ""]
    return "\n".join(head + out)


def yymmdd(s: Session) -> str:
    return (s.started or datetime.datetime.now()).strftime("%y%m%d")


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", value)[:80] or "session"


def existing(folder: Path, sid: str) -> Optional[Path]:
    hits = sorted(folder.glob("* - %s.md" % sid))
    return hits[0] if hits else None


def write_session(root: Path, source: Path, s: Session) -> Optional[Path]:
    if not any(k in ("user", "assistant") for k, _, _ in s.turns):
        return None
    where = destination(root, s)
    if where is None:
        return None
    top, projects = where
    folder = top / recall.SESSIONS_DIR
    if folder.is_symlink() or recall.synced(top):
        return None                                 # sync corrupts nothing here, and copies sessions elsewhere
    if not recall.safe_to_write(folder / "session.md"):
        return None                                 # git would see it: nothing is written
    st = source.stat()
    sid = safe_id(s.id)
    old = existing(folder, sid) if folder.is_dir() else None
    if old is not None:
        head = old.read_text(encoding="utf-8", errors="replace")[:600]
        if "source_size: %d\n" % st.st_size in head and "source_mtime: %d\n" % st.st_mtime_ns in head \
                and "format: 2\n" in head:
            return None
    text = render(s, projects, st.st_size, st.st_mtime_ns)
    if recall.session_projects(text) != [clean_name(p) for p in projects] or \
            any(clean_name(p) != p for p in projects):
        return None                                 # what is written would not read back as the same projects
    folder.mkdir(mode=0o700, exist_ok=True)
    target = old or folder / ("%s - %s.md" % (yymmdd(s), sid))
    tmp = folder / (".tmp-%d" % os.getpid())
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(str(tmp), 0o600)
    except OSError:
        pass
    os.replace(str(tmp), str(target))
    return target


def claude_files(folder: Path) -> List[Path]:
    return sorted(p for p in folder.glob("*/*.jsonl") if p.is_file()) if folder.is_dir() else []


def codex_files(folder: Path) -> List[Path]:
    found = sorted(p for p in folder.rglob("*.jsonl") if p.is_file()) if folder.is_dir() else []
    archived = folder.parent / "archived_sessions"
    if archived.is_dir():
        found += sorted(p for p in archived.glob("*.jsonl") if p.is_file())
    return found


def extract_all(root: Path, claude: Optional[str] = None, codex: Optional[str] = None) -> str:
    """Write every session not yet written, or grown since. Says how many
    were written and how many were placed nowhere, and names no zone."""
    home = Path.home()
    jobs = [(parse_claude, f) for f in claude_files(Path(claude) if claude else home / ".claude" / "projects")]
    jobs += [(parse_codex, f) for f in codex_files(Path(codex) if codex else home / ".codex" / "sessions")]
    wrote = nowhere = 0
    for parse, source in jobs:
        try:
            s = parse(source)
            if not any(k in ("user", "assistant") for k, _, _ in s.turns) or not s.cwds:
                continue
            if destination(root, s) is None:
                if any(recall.locate(root.resolve(), c) is not None for c in s.cwds if Path(c).is_absolute()):
                    nowhere += 1
                continue
            if write_session(root, source, s) is not None:
                wrote += 1
        except OSError:
            continue
    return "sessions written: %d; placed nowhere: %d" % (wrote, nowhere)
