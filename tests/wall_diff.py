"""Compare the wall check's verdicts with a release's: the gate for the token reading and for the flag model.

    python3 tests/wall_diff.py v0.59.1

Takes `check.py` and `garrick_lib.py` of the tag with `git show` into a temporary
folder, runs the generated table of `tests/test_wall_forms.py` through the tag's
check and through the working tree's, and prints three counts (the rows whose keys hold the temporary root are compared with it taken out, and counted as a group of their own): rows refused in
both, rows passed in both, and rows whose verdict changed, split into
refused -> passed and passed -> refused by page kind and wrapper.

The tag declares walls as pairs and this tree as a flag on each party, so the
fixture's context is written for the tag with a Walls table of every pair of
walled parties (`legacy_walls`). A refused -> passed row is then one of three
kinds: *by design*, a token that does not resolve (the threat model of 0.58.0);
*by the design*, a flow the flag model allows on purpose (an open party's
material into a walled scope; a source of two walled parties into a scope
naming both); or *other*. Exits 1 when *other* is not 0. `--full` runs every row (the default runs the rows the test
runs). `diff(tag)` returns the same numbers as a dict, for a test or a session.

Each side runs in a process of its own, so that two copies of `check` never
share a module table.
"""

from __future__ import annotations

import argparse
import json
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


def legacy_walls(root: Path) -> None:
    """Add to the fixture's System/context.md the Walls table a release before the flag model reads: a row for
    every pair of walled parties, and for no other."""
    path = Path(root) / "System" / "context.md"
    walled, header = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
        elif "tag" in header and "walled" in header and not set(line) <= set("|-: "):
            tag = cells[header.index("tag")].strip("`")
            if cells[header.index("walled")].lower() == "yes":
                walled.append(tag)
    walled = sorted(walled)
    rows = ["| `%s` | `%s` | pair |" % (a, b) for i, a in enumerate(walled) for b in walled[i + 1:]]
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + "\n\n## Walls\n\n| Between | And | Why |\n|---|---|---|\n"
                    + "\n".join(rows) + "\n", encoding="utf-8")


def verdicts(tools: Path, full: bool = False, legacy: bool = False) -> dict:
    """{(project, party, label): "refused" | "passed"} for the table run through
    the check in `tools`. Runs in this process: the check in `tools` must be the
    first one imported (`worker` arranges that)."""
    import tempfile as _tempfile
    import check  # the check in `tools`, already first on the path
    import test_wall_forms as forms

    assert Path(check.__file__).resolve().parent == Path(tools).resolve(), check.__file__
    with _tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "Workspace"
        if legacy:
            built = forms.build

            def build_with_pairs(where):
                pages = built(where)
                legacy_walls(where)
                return pages

            forms.build = build_with_pairs
        table = forms.Table(tools=check, root=root)
        real = table.verdict

        def verdict(project_name, text):
            try:
                return real(project_name, text)
            except Exception:                     # a check that crashes does not let a note through
                return "refused"

        table.verdict = verdict
        out = table.run(full=full)
    # A warning is not a refusal.
    return {k: ("refused" if v == "refused" else "passed") for k, v in out.items()}


def worker(tools: Path, full: bool, legacy: bool = False) -> None:
    """Child process: the check in `tools` first, then the table; JSON on stdout."""
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(tools))
    out = verdicts(tools, full, legacy)
    json.dump([[*k, v] for k, v in sorted(out.items())], sys.stdout)


def start(tools: Path, full: bool, legacy: bool = False) -> subprocess.Popen:
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(tools)] + (["--full"] if full else []) \
        + (["--legacy"] if legacy else [])
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(HERE))


# The fixture's root, as a run of the table names it in a row's label: a temporary folder, new each run.
TEMP_ROOT_RE = re.compile(r"(?:/private)?/(?:var/folders/[^/]+/[^/]+/T|var/tmp|tmp)/tmp[^/\s]*/Workspace")
TEMP = "<temp>/Workspace"


def finish(proc: subprocess.Popen) -> dict:
    """{key: verdict} for the table's rows; a row whose key holds the temporary path has that path replaced by
    TEMP, so that the two runs' rows meet, and its key's label starts with TEMP_MARK."""
    out, err = proc.communicate()
    if proc.returncode:
        raise RuntimeError("the table did not run:\n" + err[-2000:])
    rows = {}
    for p, q, label, v in json.loads(out):
        if TEMP_ROOT_RE.search(label):
            label = TEMP_MARK + TEMP_ROOT_RE.sub(TEMP, label)
        rows[(p, q, label)] = v
    return rows


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
    """(page kind, wrapper) of a row label `kind/grade/wrapper: token`."""
    kind, _, rest = label.partition("/")
    return kind, rest.split("/", 1)[-1].split(":", 1)[0]


def flags() -> dict:
    """{tag: walled} of the table's fixture, as this tree reads it."""
    import tempfile as _tempfile
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(HERE))
    import garrick_lib
    from fixtures import build_workspace
    with _tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "W"
        build_workspace(root)
        return {t: e["walled"] for t, e in garrick_lib.load_context(root)["parties"].items()}


def by_design(label: str) -> bool:
    """Is a refused -> passed row one whose token does not resolve? The table's rows all name a page that is
    there, so none is; the threat model's rows would be listed here."""
    return False


def by_the_design(party: str, scope: str, walled: dict) -> bool:
    """Is a refused -> passed row a flow the flag model allows on purpose: the page's party is open, or the
    project's scope names the party? A page of a walled party into a scope that lacks it is never one."""
    return not walled.get(party, True) or party == scope


def diff(tag: str, full: bool = False) -> dict:
    """The comparison, as numbers: {"tag", "rows", "refused_both", "passed_both", "changed",
    "refused_to_passed": {"total", "by_kind", "by_wrapper", "rows"}, "passed_to_refused": {...}}."""
    with tempfile.TemporaryDirectory() as tmp:
        old_tools = tag_tools(tag, Path(tmp) / "tag")
        procs = (start(old_tools, full, legacy=True), start(TOOLS, full))
        old, new = finish(procs[0]), finish(procs[1])
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
    walled = flags()
    scopes = {"Northwind": "acme", "Harbour": "birch"}

    def sort(keys):
        kinds = {"by_design": [], "by_the_design": [], "other": []}
        for key in keys:
            project, party, label = key
            kind = "by_design" if by_design(label) else "by_the_design" if by_the_design(party, scopes[project], walled) else "other"
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
                lines.append("    by design: %d, by the design: %d, other: %d"
                             % (kinds["by_design"], kinds["by_the_design"], kinds["other"]))
                lines += ["    " + r[:200] for r in part["other_rows"][:show]]
                if kinds["other"] > show:
                    lines.append("    ... and %d more" % (kinds["other"] - show))
    t = result["temp_path"]
    lines.append("rows with a temporary path in the key, compared with it taken out: %d" % t["rows"])
    lines += ["  refused in both:   %d" % t["refused_both"], "  passed in both:    %d" % t["passed_both"],
              "  no twin in the release: %d" % t["no_twin"],
              "  refused -> passed: %d (by design: %d, by the design: %d, other: %d)"
              % (t["refused_to_passed"]["total"], t["refused_to_passed"]["kinds"]["by_design"],
                 t["refused_to_passed"]["kinds"]["by_the_design"], t["refused_to_passed"]["kinds"]["other"]),
              "  passed -> refused: %d" % t["passed_to_refused"]["total"]]
    lines += ["    " + r[:200] for r in t["refused_to_passed"]["other_rows"][:show]]
    lines += ["    " + r[:200] for r in t["passed_to_refused"]["rows"][:show]]
    other = result["refused_to_passed"]["kinds"]["other"] + t["refused_to_passed"]["kinds"]["other"]
    lines.append("FAIL: %d rows the release refused now pass, and the design does not allow them." % other
                 if other else "OK: every row that goes from refused to passed is by design.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tag", nargs="?", help="the release tag to compare with, such as v0.58.1")
    ap.add_argument("--full", action="store_true", help="run every row, not the rows the test runs")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    ap.add_argument("--legacy", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.worker:
        worker(Path(args.worker), args.full, args.legacy)
        return 0
    if not args.tag:
        ap.error("name a tag")
    result = diff(args.tag, args.full)
    print(report(result))
    return 1 if result["refused_to_passed"]["kinds"]["other"] + result["temp_path"]["refused_to_passed"]["kinds"]["other"] else 0


if __name__ == "__main__":
    sys.exit(main())
