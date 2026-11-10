"""Compare the wall check's verdicts with a release's: the gate for the way the check reads a reference.

    python3 tests/wall_diff.py v0.62.0

Takes `check.py` and `garrick_lib.py` of the tag with `git show` into a temporary
folder, runs the rows of `tests/walls_forms.py` (one for each link form and
page kind, and each case of `tests/walls/forms/`) through the tag's check and
through the working tree's, and prints the rows whose verdict changed. A
refused -> passed row is one of four kinds: *by design*, a row whose token does
not resolve (a case file says `far: by design`; see docs/principles.md);
*inside one zone*, both ends of the reference in one zone, which the zone wall
does not read; *name only*, a name hit with no link, embed, path or copy, since
no name is read any more; or *other*. A passed -> refused row is never by
design. Exits 1 when *other* is not 0 or a row went from passed to refused.
`diff(tag)` returns the same numbers as a dict, for a test or a session.

Each side runs in a process of its own, so that two copies of `check` never
share a module table.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TOOLS = REPO / "template" / "System" / "tools"
FILES = ("check.py", "garrick_lib.py")


def verdicts(tools: Path, full: bool = False) -> dict:
    """{"rows": {(project, party, label): "refused" | "passed"}, "by_design": [label, ...]} for the rows run through
    the check in `tools`; the labels are those the working tree's case files call by design. Runs in this process:
    the check in `tools` must be the first one imported (`worker` arranges that)."""
    import tempfile as _tempfile
    import check  # the check in `tools`, already first on the path
    import walls_forms as forms

    assert Path(check.__file__).resolve().parent == Path(tools).resolve(), check.__file__
    with _tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "Workspace"
        table = forms.Table(tools=check, root=root)
        real = table.verdict

        def verdict(project_name, text):
            try:
                return real(project_name, text)
            except Exception:                     # a check that crashes does not let a note through
                return "refused"

        table.verdict = verdict
        out = table.run(full=full)
        design = sorted(k[2] for k, v in table.expected().items() if v == "by design")
    # A warning is not a refusal.
    return {"rows": {k: ("refused" if v == "refused" else "passed") for k, v in out.items()}, "by_design": design}


def worker(tools: Path, full: bool) -> None:
    """Child process: the check in `tools` first, then the rows; JSON on stdout."""
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(tools))
    out = verdicts(tools, full)
    json.dump({"rows": [[*k, v] for k, v in sorted(out["rows"].items())], "by_design": out["by_design"]}, sys.stdout)


def start(tools: Path, full: bool) -> subprocess.Popen:
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(tools)] + (["--full"] if full else [])
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(HERE))


def temp_bases() -> list:
    """Every folder a run's temporary root may be under: the system's, `TMPDIR`, the folders every Mac and Linux
    keeps, and a pytest or tempfile root, each as written and as the disk resolves it."""
    found = {"/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp", tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir()),
             os.environ.get("TMPDIR", ""), os.path.realpath(os.environ.get("TMPDIR") or "/tmp")}
    return sorted((b.rstrip("/") for b in found if b.strip("/")), key=len, reverse=True)


# The fixture's root, as a run of the rows names it in a label: a path under any temporary folder, new each run.
TEMP_ROOT_RE = re.compile(r"(?:%s|(?:/private)?/var/folders/[^/\s]+/[^/\s]+/T|[^\s]*?/pytest-of-[^/\s]+)(?:/[^/\s]+)*?/Workspace"
                          % "|".join(re.escape(b) for b in temp_bases()))
TEMP = "<temp>/Workspace"


def finish(proc: subprocess.Popen) -> dict:
    """{"rows": {key: verdict}, "by_design": set of labels}; a row whose label holds a temporary path has that path
    replaced by TEMP, so that the two runs' rows meet, and its label starts with TEMP_MARK."""
    out, err = proc.communicate()
    if proc.returncode:
        raise RuntimeError("the rows did not run:\n" + err[-2000:])
    loaded = json.loads(out)
    rows = {}
    for p, q, label, v in loaded["rows"]:
        if TEMP_ROOT_RE.search(label):
            label = TEMP_MARK + TEMP_ROOT_RE.sub(TEMP, label)
        rows[(p, q, label)] = v
    return {"rows": rows, "by_design": set(loaded["by_design"])}


TEMP_MARK = "[temp path] "


def tag_tools(tag: str, into: Path) -> Path:
    """The tag's check.py and garrick_lib.py, taken with `git show` into `into`."""
    into.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shown = subprocess.run(["git", "show", "%s:template/System/tools/%s" % (tag, name)], cwd=str(REPO),
                               capture_output=True)
        if shown.returncode:
            raise SystemExit("git show %s:%s failed: %s" % (tag, name, shown.stderr.decode(errors="replace").strip()))
        (into / name).write_bytes(shown.stdout)
    return into


def split(label: str):
    """(page kind, link form) of a row label `kind/grade/form`; a case file's row is `form/<round>/<n> <name>`."""
    parts = label.split("/", 2)
    return parts[0], parts[-1]


def zones() -> dict:
    """{tag: zone} of the table's fixture, as this tree reads it."""
    import tempfile as _tempfile
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(HERE))
    import garrick_lib
    from fixtures import build_workspace
    with _tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "W"
        build_workspace(root)
        return {t: e["zone"] for t, e in garrick_lib.load_context(root)["parties"].items()}


def by_design(label: str, design: set) -> bool:
    """Is a refused -> passed row one whose token does not resolve? The case files say so: `far: by design`."""
    return label in design


NAME_ONLY = ("cedar-zone/prose",)       # a party named in prose, with no link, embed, path or copy: no name is read


def inside_one_zone(project: str, party: str, where: dict) -> bool:
    """Is a refused -> passed row a reference with both ends in one zone: the project's zone is the zone of the page's
    party? The fixture's projects are all in the Work zone."""
    return where.get(party) == "Work"


def diff(tag: str, full: bool = False) -> dict:
    """The comparison, as numbers: {"tag", "rows", "refused_both", "passed_both", "changed",
    "refused_to_passed": {"total", "by_kind", "by_wrapper", "rows"}, "passed_to_refused": {...}}."""
    with tempfile.TemporaryDirectory() as tmp:
        old_tools = tag_tools(tag, Path(tmp) / "tag")
        procs = (start(old_tools, full), start(TOOLS, full))
        old, now_run = finish(procs[0]), finish(procs[1])
    old, new, design = old["rows"], now_run["rows"], now_run["by_design"]
    temp = {k for k in new if k[2].startswith(TEMP_MARK)}
    result = {"tag": tag, "rows": len(new) - len(temp), "refused_both": 0, "passed_both": 0}
    moved = {"refused_to_passed": [], "passed_to_refused": []}
    group = {"rows": len(temp), "refused_both": 0, "passed_both": 0, "no_twin": 0,
             "refused_to_passed": [], "passed_to_refused": []}
    for key, now in new.items():
        before = old.get(key)
        if before is None:
            if key in temp:
                group["no_twin"] += 1
            continue                                   # a row the tag has no twin for
        if before == now:
            target = group if key in temp else result
            target["refused_both" if now == "refused" else "passed_both"] += 1
        else:
            (group if key in temp else moved)["refused_to_passed" if before == "refused" else "passed_to_refused"].append(key)
    for name, keys in moved.items():
        result[name] = {"total": len(keys),
                        "by_kind": dict(Counter(split(k[2])[0] for k in keys)),
                        "by_wrapper": dict(Counter(split(k[2])[1] for k in keys)),
                        "rows": ["%s reads %s: %s" % k for k in sorted(keys)]}
    result["changed"] = sum(result[n]["total"] for n in moved)
    where = zones()

    def sort(keys):
        kinds = {"by_design": [], "inside_one_zone": [], "name_only": [], "other": []}
        for key in keys:
            project, party, label = key
            kind = ("by_design" if by_design(label, design) else "name_only" if label in NAME_ONLY
                    else "inside_one_zone" if inside_one_zone(project, party, where) else "other")
            kinds[kind].append(key)
        return kinds

    kinds = sort(moved["refused_to_passed"])
    result["refused_to_passed"]["kinds"] = {k: len(v) for k, v in kinds.items()}
    result["refused_to_passed"]["other_rows"] = ["%s reads %s: %s" % k for k in sorted(kinds["other"])]
    # The rows whose keys hold the temporary path: compared with that path taken out, and a group of their own.
    tkinds = sort(group["refused_to_passed"])
    result["temp_path"] = {
        "rows": group["rows"], "refused_both": group["refused_both"], "passed_both": group["passed_both"],
        "no_twin": group["no_twin"],
        "refused_to_passed": {"total": len(group["refused_to_passed"]), "kinds": {k: len(v) for k, v in tkinds.items()},
                              "other_rows": ["%s reads %s: %s" % k for k in sorted(tkinds["other"])]},
        "passed_to_refused": {"total": len(group["passed_to_refused"]),
                              "rows": ["%s reads %s: %s" % k for k in sorted(group["passed_to_refused"])]},
    }
    return result


def report(result: dict, show: int = 20) -> str:
    lines = ["Wall check against %s, %d rows" % (result["tag"], result["rows"]),
             "refused in both:   %d" % result["refused_both"],
             "passed in both:    %d" % result["passed_both"],
             "changed:           %d" % result["changed"]]
    for name, arrow in (("refused_to_passed", "refused -> passed"), ("passed_to_refused", "passed -> refused")):
        part = result[name]
        lines.append("  %s: %d" % (arrow, part["total"]))
        if part["total"]:
            for title, counts in (("page kind", part["by_kind"]), ("wrapper", part["by_wrapper"])):
                lines.append("    by %s: %s" % (title, ", ".join("%s %d" % kv for kv in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))))
            if name == "refused_to_passed":
                kinds = part["kinds"]
                lines.append("    by design: %d, inside one zone: %d, name only: %d, other: %d"
                             % (kinds["by_design"], kinds["inside_one_zone"], kinds["name_only"], kinds["other"]))
                lines += ["    " + r[:200] for r in part["other_rows"][:show]]
                if kinds["other"] > show:
                    lines.append("    ... and %d more" % (kinds["other"] - show))
    t = result["temp_path"]
    lines.append("rows with a temporary path in the key, compared with it taken out: %d" % t["rows"])
    lines += ["  refused in both:   %d" % t["refused_both"], "  passed in both:    %d" % t["passed_both"],
              "  no twin in the release: %d" % t["no_twin"],
              "  refused -> passed: %d (by design: %d, inside one zone: %d, name only: %d, other: %d)"
              % (t["refused_to_passed"]["total"], t["refused_to_passed"]["kinds"]["by_design"],
                 t["refused_to_passed"]["kinds"]["inside_one_zone"], t["refused_to_passed"]["kinds"]["name_only"],
                 t["refused_to_passed"]["kinds"]["other"]),
              "  passed -> refused: %d" % t["passed_to_refused"]["total"]]
    lines += ["    " + r[:200] for r in t["refused_to_passed"]["other_rows"][:show]]
    lines += ["    " + r[:200] for r in t["passed_to_refused"]["rows"][:show]]
    other = result["refused_to_passed"]["kinds"]["other"] + t["refused_to_passed"]["kinds"]["other"]
    worse = result["passed_to_refused"]["total"] + t["passed_to_refused"]["total"]
    lines.append("FAIL: %d rows the release refused now pass, and the design does not allow them." % other if other
                 else "FAIL: %d rows the release passed are now refused." % worse if worse
                 else "OK: every row that goes from refused to passed is by design, inside one zone or name only.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tag", nargs="?", help="the release tag to compare with, such as v0.60.1")
    ap.add_argument("--full", action="store_true", help="run every row, not the rows the test runs")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        worker(Path(args.worker), args.full)
        return 0
    if not args.tag:
        ap.error("name a tag")
    result = diff(args.tag, args.full)
    print(report(result))
    worse = result["passed_to_refused"]["total"] + result["temp_path"]["passed_to_refused"]["total"]
    return 1 if worse or result["refused_to_passed"]["kinds"]["other"] + result["temp_path"]["refused_to_passed"]["kinds"]["other"] else 0


if __name__ == "__main__":
    sys.exit(main())
