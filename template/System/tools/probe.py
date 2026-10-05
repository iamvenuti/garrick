#!/usr/bin/env python3
"""What this Mac has that Garrick can use, for the setup skill.

    python3 System/tools/probe.py            one line per finding
    python3 System/tools/probe.py --json     the same, for a program

Read-only. It looks at installed apps, commands on the PATH, git's settings
for this workspace, and folders inside it. It opens no file of yours, changes
nothing, and sends nothing anywhere. Which assistant and app the user works in
is not here: the assistant running the setup knows that, and asks the rest.

Standard library only, Python 3.9 or later.
"""

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from garrick_lib import LOCAL_EMAIL, hooks_path, workspace_root  # noqa: E402

# Apps Garrick can work with: key, what it is, bundle ids, the names its .app may carry.
APPS = (
    ("claude", "the Claude app", ("com.anthropic.claudefordesktop",), ("Claude",)),
    ("codex", "the Codex app", ("com.openai.codex",), ("Codex",)),
    ("chatgpt", "the ChatGPT app", ("com.openai.chat",), ("ChatGPT",)),
    ("cmux", "cmux", ("com.cmuxterm.app",), ("cmux",)),
    ("obsidian", "Obsidian", ("md.obsidian",), ("Obsidian",)),
)
# Commands on the PATH: key, what it is.
COMMANDS = (("claude", "Claude Code in a terminal"), ("codex", "Codex in a terminal"), ("cmux", "cmux's command"),
            ("gh", "GitHub's command"))


def app_folders(home: Path) -> List[Path]:
    return [Path("/Applications"), home / "Applications", Path("/System/Applications")]


def bundle_id(app: Path) -> Optional[str]:
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            return plistlib.load(f).get("CFBundleIdentifier")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def find_apps(folders: List[Path]) -> Dict[str, str]:
    """{key: path} for each of APPS found. An app is known by its bundle id, so
    one app is never taken for another; one with no readable Info.plist is
    taken at its name."""
    found = {}
    for key, _, bundles, names in APPS:
        for folder in folders:
            for name in names:
                app = folder / (name + ".app")
                if app.is_dir() and bundle_id(app) in bundles + (None,):
                    found[key] = str(app)
                    break
            if key in found:
                break
    return found


def git_setting(root: Path, key: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), "config", "--get", key], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def version_of(command: str) -> str:
    try:
        r = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 and (r.stdout or r.stderr).strip() else ""


def probe(root: Path, home: Optional[Path] = None, path: Optional[str] = None) -> dict:
    home = home or Path.home()
    mac = platform.mac_ver()[0]
    apps = find_apps(app_folders(home)) if sys.platform == "darwin" else {}
    commands = {key: shutil.which(key, path=path) or "" for key, _ in COMMANDS}
    zones = sorted(d.name for d in (root / "Zones").iterdir()
                   if d.is_dir() and not d.name.startswith((".", "_"))) if (root / "Zones").is_dir() else []
    repos = [root, root / "Wikis"] + [root / "Zones" / z for z in zones]
    vaults = [str(p.parent.relative_to(root)) or "." for p in [root / ".obsidian", root / "Wikis" / ".obsidian"]
              + [root / "Zones" / z / ".obsidian" for z in zones] if p.is_dir()]
    vaults = ["the workspace" if v == "." else v for v in vaults]
    email = git_setting(root, "user.email")
    return {
        "macos": mac,
        "python": platform.python_version(),
        "git": version_of("git"),
        "apps": apps,
        "commands": {k: v for k, v in commands.items() if v},
        "git_identity": {"name": git_setting(root, "user.name"), "email": email,
                         "garrick_address": email == LOCAL_EMAIL},
        "hooks_skipped": [str(r.relative_to(root)) if r != root else "the workspace"
                          for r in repos if (r / ".git").exists() and hooks_path(r)],
        "obsidian_vaults": vaults,
        "zones": zones,
    }


def say(found: dict) -> str:
    """One line per finding, in words the setup skill can read back."""
    names = {key: label for key, label, _, _ in APPS}
    commands = dict(COMMANDS)
    lines = ["macOS %s, Python %s, %s." % (found["macos"] or "unknown", found["python"], found["git"] or "git missing")]
    apps = [names[k] for k in names if k in found["apps"]]
    lines.append("Apps: %s." % (", ".join(apps) if apps else "none of Claude, Codex, ChatGPT, cmux or Obsidian"))
    cmds = [commands[k] for k in commands if k in found["commands"]]
    lines.append("Commands: %s." % (", ".join(cmds) if cmds else "none of claude, codex, cmux or gh"))
    ident = found["git_identity"]
    if ident["garrick_address"]:
        lines.append("git saves history here as %s, at %s: git had no address of its own." % (ident["name"], LOCAL_EMAIL))
    elif ident["email"]:
        lines.append("git saves history here as %s <%s>." % (ident["name"], ident["email"]))
    else:
        lines.append("git has no name or address here, so saving history will fail until one is set.")
    if found["hooks_skipped"]:
        lines.append("git skips the wall check in: %s." % ", ".join(found["hooks_skipped"]))
    if "obsidian" in found["apps"]:
        lines.append("Obsidian vaults here: %s." % (", ".join(found["obsidian_vaults"]) or "none yet"))
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="What this Mac has that Garrick can use. Read-only.")
    ap.add_argument("--root", help="the workspace (default: the one this script sits in)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        root = Path(args.root).expanduser().resolve() if args.root else workspace_root(HERE)
    except FileNotFoundError:
        print("This script is not inside a Garrick workspace.", file=sys.stderr)
        return 2
    found = probe(root)
    print(json.dumps(found, indent=2) if args.json else say(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
