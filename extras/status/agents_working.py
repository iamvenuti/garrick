#!/usr/bin/env python3
"""Is an assistant mid-turn right now? Garrick.app's *Keep awake › While an
agent is working* runs this once a minute (preview: menu-bar).

    python3 agents_working.py [--verbose]

Exit 0 when at least one session is working, 1 when none is, 2 when it cannot
tell (no transcript folder can be read). It reads the transcripts Claude Code
and Codex write, never a socket or a model: Claude Code's in
~/.claude/projects/*/*.jsonl, Codex's in ~/.codex/sessions/**/*.jsonl. Only a
transcript written in the last 30 minutes counts, so a session that crashed
mid-turn stops counting; a single tool call that runs longer than that without
a word lets the Mac sleep. Each one is read from its last 256 KB: Claude Code's
turn is over once a turn_duration or local_command record follows the last
prompt or tool result, Codex's once task_complete or turn_aborted follows
task_started. --verbose prints each recent transcript's state.
"""
import json
import sys
import time
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

RECENT = 30 * 60
TAIL = 256 * 1024


def records(path: Path) -> Iterator[dict]:
    """The JSON records at the end of a transcript; a line cut by the tail is skipped."""
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL))
        lines = f.read().split(b"\n")
    for line in lines[1:] if size > TAIL else lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def state(path: Path) -> str:
    """working, idle, or ? when the transcript says neither."""
    found = "?"
    for d in records(path):
        kind = d.get("type")
        if kind == "event_msg":                                       # Codex
            event = (d.get("payload") or {}).get("type") if isinstance(d.get("payload"), dict) else None
            if event == "task_started":
                found = "working"
            elif event in ("task_complete", "turn_aborted"):
                found = "idle"
        elif kind == "user" and not d.get("isMeta"):                  # Claude Code: a prompt or a tool result
            content = (d.get("message") or {}).get("content")
            text = content if isinstance(content, str) else " ".join(
                x.get("text", "") for x in content or [] if isinstance(x, dict))
            found = "idle" if "[Request interrupted" in text else "working"
        elif kind == "system" and d.get("subtype") in ("turn_duration", "local_command"):
            found = "idle"
    return found


def recent(home: Path, now: Optional[float] = None) -> Optional[List[Path]]:
    """Transcripts written in the last RECENT seconds, or None when neither folder exists."""
    now = time.time() if now is None else now
    folders = [(home / ".claude" / "projects", "*/*.jsonl"), (home / ".codex" / "sessions", "**/*.jsonl")]
    if not any(folder.is_dir() for folder, _ in folders):
        return None
    out = []
    for folder, pattern in folders:
        for path in folder.glob(pattern) if folder.is_dir() else []:
            try:
                if now - path.stat().st_mtime <= RECENT:
                    out.append(path)
            except OSError:
                continue
    return out


def check(home: Path, now: Optional[float] = None) -> Tuple[int, List[Tuple[str, Path]]]:
    paths = recent(home, now)
    if paths is None:
        return 2, []
    seen = []
    for path in paths:
        try:
            seen.append((state(path), path))
        except OSError:
            continue
    return (0 if any(s == "working" for s, _ in seen) else 1), seen


def main(argv: List[str]) -> int:
    code, seen = check(Path.home())
    if "--verbose" in argv:
        if code == 2:
            print("cannot tell: no Claude Code or Codex transcripts on this Mac")
        for s, path in seen:
            print("%-8s %s" % (s, path))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
