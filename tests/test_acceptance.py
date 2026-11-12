"""Tests for the acceptance run, tests/acceptance/run.py (#513).

    python3 -m unittest test_acceptance

The full run is not a unit test: CI runs it on release pull requests. What is
checked here is fast and offline: the Ask set is well formed, the run's
environment holds nothing of the machine it runs on, a step that needs a failed
one is skipped, and one broken step, the demo's page rebuild removed, makes the
run fail at that step and at no other.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
RUN = REPO / "tests" / "acceptance" / "run.py"
SET = REPO / "tests" / "acceptance" / "ask_set.json"

sys.path.insert(0, str(RUN.parent))
import run as acceptance  # noqa: E402


def candidate_zip(path, edit=None):
    """The working tree as a release zip would hold it, `garrick/` first, so an uncommitted change
    is in it. `edit` takes (name, bytes) and returns the bytes to write."""
    names = subprocess.run(["git", "ls-files", "-z"], cwd=str(REPO), capture_output=True, check=True).stdout.split(b"\0")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for raw in names:
            name = raw.decode("utf-8")
            src = REPO / name
            if not name or not src.is_file() or src.is_symlink():
                continue
            data = src.read_bytes()
            if edit:
                data = edit(name, data)
            z.writestr("garrick/" + name, data)


def run_acceptance(*args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, env=env, timeout=1500)


class AskSetTest(unittest.TestCase):
    def test_the_set_is_about_fifteen_questions_of_the_kinds_the_issue_names(self):
        qs = json.loads(SET.read_text(encoding="utf-8"))["questions"]
        self.assertGreaterEqual(len(qs), 14)
        self.assertLessEqual(len(qs), 16)
        self.assertEqual(len({q["id"] for q in qs}), len(qs))
        kinds = {q["kind"] for q in qs}
        for kind in ("lately", "recently", "ambiguous", "corrected", "two zones", "no answer"):
            self.assertIn(kind, kinds)
        for q in qs:
            self.assertIn(q["find"]["route"], ("meetings", "thread", "knowledge", "docs"), q["id"])
            self.assertIn(q["expect"]["outcome"], ("records", "none", "asks"), q["id"])
            self.assertTrue(q["q"].endswith(("?", "Cobalt")), q["id"])

    def test_a_question_across_two_zones_is_asked_in_each_window_and_holds_the_wall(self):
        qs = {q["id"]: q for q in json.loads(SET.read_text(encoding="utf-8"))["questions"]}
        birch, acme = qs["wall-birch-side"]["expect"], qs["wall-acme-side"]["expect"]
        self.assertNotEqual(birch["any"], acme["any"])
        self.assertEqual(birch["none"], acme["any"])      # each window reads its own side and never the other's
        self.assertEqual(acme["none"], birch["any"])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_ = acceptance.Run(mock.Mock(model="stub", workdir=str(Path(tmp) / "w"), candidate=None, commit=None,
                                                 steps=None, compare=None, previous=None))

    def row(self, **kw):
        return dict({"outcome": "records", "paths": ["a/one.md", "b/two.md"], "wall": False, "texts": ["alpha", "beta"]}, **kw)

    def test_a_row_that_meets_its_expectations_has_no_failures(self):
        q = {"expect": {"outcome": "records", "first": "one", "any": ["two"], "none": ["three"], "wall": False}}
        self.assertEqual(self.run_.judge(q, self.row()), [])

    def test_each_expectation_can_fail(self):
        self.assertTrue(self.run_.judge({"expect": {"outcome": "none"}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"first": "two"}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"any": ["nine"]}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"none": ["two"]}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"wall": True}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"first": "one", "has": ["gamma"]}}, self.row()))
        self.assertTrue(self.run_.judge({"expect": {"first": "one", "lacks": ["alpha"]}}, self.row()))


class EnvironmentTest(unittest.TestCase):
    def test_the_environment_holds_nothing_of_the_machine_it_runs_on(self):
        host = {"GARRICK_WORKSPACE": "/host/ws", "GARRICK_JOBS_DIR": "/host/jobs", "CLAUDE_CONFIG_DIR": "/host/claude",
                "CMUX_SURFACE_ID": "x", "ANTHROPIC_API_KEY": "k", "XDG_STATE_HOME": "/host/state", "HOME": "/host/home"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, host):
            r = acceptance.Run(mock.Mock(model="stub", workdir=str(Path(tmp) / "w"), candidate=None, commit=None,
                                         steps=None, compare=None, previous=None))
            env = r.env
            inside = str(Path(tmp).resolve())
            for key in ("HOME", "GARRICK_HOME", "GARRICK_JOBS_DIR"):
                self.assertTrue(env[key].startswith(inside), key)
            for key in ("GARRICK_WORKSPACE", "CLAUDE_CONFIG_DIR", "CMUX_SURFACE_ID", "ANTHROPIC_API_KEY", "XDG_STATE_HOME"):
                self.assertNotIn(key, env)
            # The assistant's sign-in goes on only to a model run, and its state stays inside the folder.
            claude = r.claude_env()
            self.assertEqual(claude["ANTHROPIC_API_KEY"], "k")
            self.assertTrue(claude["CLAUDE_CONFIG_DIR"].startswith(inside))

    def test_every_step_the_docstring_names_exists(self):
        doc = acceptance.__doc__
        for key in acceptance.STEPS:
            self.assertTrue(hasattr(acceptance.Run, "step_" + key), key)
            self.assertRegex(doc, r"(?m)^    %s\s" % key)

    def test_a_step_that_is_not_one_is_refused(self):
        r = run_acceptance("--steps", "install,nonsense")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("not a step", r.stderr)


class WiringTest(unittest.TestCase):
    def test_the_release_steps_and_the_workflow_name_the_run(self):
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("tests/acceptance/run.py --candidate /tmp/garrick.zip", agents)
        self.assertIn("--strict", agents)
        self.assertLess(agents.index("tests/acceptance/run.py"), agents.index("gh release create"))
        flow = (REPO / ".github" / "workflows" / "acceptance.yml").read_text(encoding="utf-8")
        self.assertIn("tests/acceptance/run.py --model stub", flow)
        self.assertIn("startsWith(github.head_ref, 'release-')", flow)
        self.assertIn("workflow_dispatch", flow)
        self.assertIn("macos-latest", flow)


class ReviewFixesTest(unittest.TestCase):
    def args(self, **kw):
        return mock.Mock(model="stub", candidate=None, commit=None, steps=None, compare=None, previous=None, **kw)

    def test_the_previous_tag_is_never_the_candidates_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            repo.mkdir()
            env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@x", GIT_COMMITTER_NAME="a",
                       GIT_COMMITTER_EMAIL="a@x")

            def git(*a):
                return subprocess.run(["git", "-C", str(repo), *a], env=env, capture_output=True, text=True, check=True)
            git("init", "-q")
            for n, tag in ((1, "v0.1.0"), (2, "v0.2.0"), (3, None)):
                (repo / "f").write_text(str(n))
                git("add", "-A")
                git("commit", "-q", "-m", str(n))
                if tag:
                    git("tag", tag)
            git("tag", "v0.3.0")
            with mock.patch.object(acceptance, "REPO", repo), mock.patch.object(acceptance, "sh", wraps=acceptance.sh):
                r = acceptance.Run(self.args(workdir=str(Path(tmp) / "w")))
                r.args.commit = "v0.3.0"
                self.assertEqual("v0.2.0", r.previous_tag())      # the candidate's own tag is skipped
                r.args.commit = "v0.2.0"
                self.assertEqual("v0.1.0", r.previous_tag())
                r.args.commit = "v0.1.0"
                with self.assertRaises(acceptance.Fail):
                    r.previous_tag()

    def test_the_headline_names_what_was_skipped_and_strict_fails_on_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = acceptance.Run(self.args(workdir=str(Path(tmp) / "w")))
            r.commit = "x"
            ok, sk = acceptance.Step("a", "Alpha"), acceptance.Step("b", "Beta")
            ok.status, sk.status, sk.why = "pass", "skipped", "no tag"
            r.steps = [ok, sk]
            self.assertIn("Passed, with 1 skipped: Beta.", r.report())
        for flag, code in (([], 0), (["--strict"], 1)):
            res = run_acceptance("--steps", "resume", *flag)
            self.assertEqual(code, res.returncode, res.stdout)
            self.assertIn("Passed, with 11 skipped", res.stdout)

    def test_the_refused_save_must_be_the_walls_sentence(self):
        src = RUN.read_text(encoding="utf-8")
        self.assertIn('startswith(WALL_SAID)', src)
        self.assertEqual("A wall holds some material back from this project", acceptance.WALL_SAID)

    def test_the_resume_page_check_reads_the_action_text_alone(self):
        src = RUN.read_text(encoding="utf-8")
        self.assertNotIn('"Next action" not in self.page(root)', src)


class BrokenStepTest(unittest.TestCase):
    """Breaking one step on a branch makes the run fail at that step (#513, Done when)."""

    def test_no_page_rebuild_after_the_demo_build_fails_the_demo_step_and_no_other(self):
        seen = []

        def edit(name, data):
            if name == "examples/demo/build.py":
                text = data.decode("utf-8")
                broken = re.sub(r"(?m)^    rebuild_page\(root\)$", "    pass", text)
                seen.append(broken != text)
                return broken.encode("utf-8")
            return data

        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "candidate.zip"
            candidate_zip(zpath, edit)
            self.assertEqual(seen, [True], "the demo builder has no rebuild_page(root) call to remove")
            report = Path(tmp) / "report.md"
            # The steps after the demo need it, and are skipped when it fails; the others are not selected.
            r = run_acceptance("--candidate", str(zpath), "--steps", "demo,file,brief,wrap,resume,ask", "--report", str(report),
                               "--workdir", str(Path(tmp) / "work"))
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            rows = {}
            for line in report.read_text(encoding="utf-8").splitlines():
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) == 3 and cells[1] in ("pass", "FAIL", "skipped"):
                    rows[cells[0]] = cells[1:]
            failed = [name for name, (result, _) in rows.items() if result == "FAIL"]
            self.assertEqual(failed, ["Build the demo"], rows)
            self.assertIn("after the replay", rows["Build the demo"][1])
            for name in ("File one conversation", "Ask for a brief", "Wrap a thread", "Resume the thread", "The fixed Ask set"):
                self.assertEqual(rows[name][0], "skipped", name)
                self.assertIn("needs the", rows[name][1])


if __name__ == "__main__":
    unittest.main()
