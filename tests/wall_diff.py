"""Compare the wall check's verdicts with a release's: the gate for the token reading.

    python3 tests/wall_diff.py v0.58.1

Takes `check.py` and `garrick_lib.py` of the tag with `git show` into a temporary
folder, runs the generated table of `tests/test_wall_forms.py` through the tag's
check and through the working tree's, and prints three counts: rows refused in
both, rows passed in both, and rows whose verdict changed, split into
refused -> passed and passed -> refused by page kind and wrapper. Exits 1 when
any row goes from refused to passed: a row the tag refused and this tree lets
through. A form the tag also lets through is a factor for the next release,
not a blocker. `--full` runs every row (the default runs the rows the test
runs). `diff(tag)` returns the same numbers as a dict, for a test or a session.

Each side runs in a process of its own, so that two copies of `check` never
share a module table.
"""

from __future__ import annotations

import argparse
import json
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
    """{(project, party, label): "refused" | "passed"} for the table run through
    the check in `tools`. Runs in this process: the check in `tools` must be the
    first one imported (`worker` arranges that)."""
    import tempfile as _tempfile
    import check  # the check in `tools`, already first on the path
    import test_wall_forms as forms

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
    # A warning is not a refusal.
    return {k: ("refused" if v == "refused" else "passed") for k, v in out.items()}


def worker(tools: Path, full: bool) -> None:
    """Child process: the check in `tools` first, then the table; JSON on stdout."""
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(tools))
    out = verdicts(tools, full)
    json.dump([[*k, v] for k, v in sorted(out.items())], sys.stdout)


def start(tools: Path, full: bool) -> subprocess.Popen:
    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(tools)] + (["--full"] if full else [])
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(HERE))


def finish(proc: subprocess.Popen) -> dict:
    out, err = proc.communicate()
    if proc.returncode:
        raise RuntimeError("the table did not run:\n" + err[-2000:])
    return {(p, q, label): v for p, q, label, v in json.loads(out)}


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


def diff(tag: str, full: bool = False) -> dict:
    """The comparison, as numbers: {"tag", "rows", "refused_both", "passed_both", "changed",
    "refused_to_passed": {"total", "by_kind", "by_wrapper", "rows"}, "passed_to_refused": {...}}."""
    with tempfile.TemporaryDirectory() as tmp:
        old_tools = tag_tools(tag, Path(tmp) / "tag")
        procs = (start(old_tools, full), start(TOOLS, full))
        old, new = finish(procs[0]), finish(procs[1])
    result = {"tag": tag, "rows": len(new), "refused_both": 0, "passed_both": 0}
    moved = {"refused_to_passed": [], "passed_to_refused": []}
    for key, now in new.items():
        before = old.get(key)
        if before is None:
            continue                                   # a row the tag has no twin for
        if before == now:
            result["refused_both" if now == "refused" else "passed_both"] += 1
        else:
            moved["refused_to_passed" if before == "refused" else "passed_to_refused"].append(key)
    for name, keys in moved.items():
        result[name] = {"total": len(keys),
                        "by_kind": dict(Counter(split(k[2])[0] for k in keys)),
                        "by_wrapper": dict(Counter(split(k[2])[1] for k in keys)),
                        "rows": ["%s reads %s: %s" % k for k in sorted(keys)]}
    result["changed"] = sum(result[n]["total"] for n in moved)
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
                lines += ["    " + r[:200] for r in part["rows"][:show]]
                if part["total"] > show:
                    lines.append("    ... and %d more" % (part["total"] - show))
    lines.append("FAIL: %d rows the release refused now pass." % result["refused_to_passed"]["total"]
                 if result["refused_to_passed"]["total"] else "OK: no row goes from refused to passed.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tag", nargs="?", help="the release tag to compare with, such as v0.58.1")
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
    return 1 if result["refused_to_passed"]["total"] else 0


if __name__ == "__main__":
    sys.exit(main())
