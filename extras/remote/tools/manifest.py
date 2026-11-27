#!/usr/bin/env python3
"""manifest.py: what a remote assistant may do, one row for each thing Garrick can do.

`extras/remote/manifest.json` lists every verb in `operations.DECLARED`, every
shipped skill, and the five read tools, each with one disposition:

    served          a remote assistant can use it now
    owner-approval  runs only after the owner approves that exact operation;
                    refused until that route exists
    not-yet         an ordinary remote verb, planned for a later release
    internal        no tool: the service uses it, or it has no remote meaning

and the release that plans it: `now`, `next`, `later`, or `none` for an
internal row. The tools the service registers come from the `served` rows,
so no verb is served by accident, and `check()` fails when the list and the
code disagree. The docs table is `table()`, printed by

    python3 -m tools.manifest            (from extras/remote)

Standard library only: this module runs on the Python that macOS ships.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
MANIFEST = HERE.parent / "manifest.json"
DISPOSITIONS = ("served", "owner-approval", "not-yet", "internal")
KINDS = ("verb", "skill", "read-tool")
RELEASES = ("now", "next", "later", "none")
READ_TOOLS = ("places", "thread_state", "search", "read", "owed")
WHEN = {"now": "now", "next": "in the next release", "later": "in a later release"}


def load(path=None) -> dict:
    """The manifest as a dict with its `rows`. Raises ValueError when it is not one."""
    data = json.loads(Path(path or MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("the manifest has no rows")
    return data


def rows(manifest: dict, kind=None) -> list:
    return [r for r in manifest["rows"] if kind in (None, r.get("kind"))]


def served_verbs(manifest: dict) -> list:
    """The verbs a write tool may carry out, in the manifest's order."""
    return [r["name"] for r in rows(manifest, "verb") if r["disposition"] == "served"]


def served_tools(manifest: dict) -> list:
    """The read tools the manifest serves."""
    return [r["name"] for r in rows(manifest, "read-tool") if r["disposition"] == "served"]


def row_for(manifest: dict, name: str, kind="verb"):
    for r in manifest["rows"]:
        if r.get("name") == name and r.get("kind") == kind:
            return r
    return None


def declared_verbs(operations) -> list:
    """The verbs of an `operations` module (DECLARED)."""
    return list(operations.DECLARED)


def check(manifest: dict, declared, skills=()) -> list:
    """What is wrong, as plain sentences; an empty list when the manifest is whole.
    `declared` is the verbs of operations.DECLARED, `skills` the shipped skill names."""
    bad = []
    seen = set()
    for r in manifest.get("rows", []):
        key = (r.get("kind"), r.get("name"))
        if key in seen:
            bad.append("%s %s is listed twice" % key)
        seen.add(key)
        if r.get("kind") not in KINDS:
            bad.append("%s has no kind" % r.get("name"))
        if r.get("disposition") not in DISPOSITIONS:
            bad.append("%s has no disposition" % r.get("name"))
        if r.get("release") not in RELEASES:
            bad.append("%s has no release" % r.get("name"))
        if r.get("disposition") in ("internal", "owner-approval") and not str(r.get("reason") or "").strip():
            bad.append("%s has no reason" % r.get("name"))
        if r.get("disposition") == "served" and r.get("release") != "now":
            bad.append("%s is served, so its release is now" % r.get("name"))
        if r.get("disposition") != "served" and r.get("release") == "now":
            bad.append("%s is not served, so its release is not now" % r.get("name"))
    listed = {r.get("name") for r in manifest.get("rows", []) if r.get("kind") == "verb"}
    for v in declared:
        if v not in listed:
            bad.append("the verb %s is declared and the manifest does not list it" % v)
    for v in sorted(listed - set(declared)):
        bad.append("the manifest lists %s, which is not a declared verb" % v)
    listed_skills = {r.get("name") for r in manifest.get("rows", []) if r.get("kind") == "skill"}
    for s in skills:
        if s not in listed_skills:
            bad.append("the skill %s is shipped and the manifest does not list it" % s)
    for s in sorted(listed_skills - set(skills)):
        bad.append("the manifest lists the skill %s, which is not shipped" % s)
    tools = {r.get("name") for r in manifest.get("rows", []) if r.get("kind") == "read-tool"}
    if tools != set(READ_TOOLS):
        bad.append("the read tools in the manifest are not the five the service has")
    return bad


def answer(manifest: dict, verb) -> str:
    """The plain words for a request of a verb the service does not serve: why not, and when."""
    r = row_for(manifest, str(verb)[:80])
    if r is None or r["disposition"] == "served":
        return "That is not something this service does."
    name = r["name"]
    if r["disposition"] == "owner-approval":
        return ("%s runs only after the owner approves it, and that route does not exist yet. %s"
                % (name, r.get("reason", "")))
    if r["disposition"] == "internal":
        return "%s is not offered to an assistant. %s" % (name, r.get("reason", ""))
    return "%s is not available from a remote assistant yet. It is planned %s." % (name, WHEN.get(r["release"], "for a later release"))


def table(manifest: dict) -> str:
    """The docs table, as Markdown: every row of the manifest, grouped by disposition."""
    out = ["| What | Kind | Disposition | Planned | Why |", "|---|---|---|---|---|"]
    order = {d: i for i, d in enumerate(DISPOSITIONS)}
    kinds = {k: i for i, k in enumerate(KINDS)}
    listing = sorted(manifest["rows"], key=lambda r: (order[r["disposition"]], kinds[r["kind"]], r["name"]))
    label = {"served": "Served", "owner-approval": "Owner approval", "not-yet": "Not yet", "internal": "Internal"}
    for r in listing:
        out.append("| `%s` | %s | %s | %s | %s |" % (
            r["name"], r["kind"].replace("-", " "), label[r["disposition"]],
            {"now": "now", "none": ""}.get(r["release"], WHEN.get(r["release"], "")), (r.get("reason") or "").replace("|", "/")))
    return "\n".join(out) + "\n"


def counts(manifest: dict) -> dict:
    out = {d: 0 for d in DISPOSITIONS}
    for r in rows(manifest, "verb"):
        out[r["disposition"]] += 1
    return out


def main(argv=None) -> int:
    sys.stdout.write(table(load()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
