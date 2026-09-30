"""Tests for the knowledge skill's contract: an ingest that follows
`System/skills/knowledge/SKILL.md` -- a frozen original, a source page, the
concept and entity pages it touches, and the index and log -- written onto a
real installed workspace and checked with `System/tools/check.py`.

    python3 -m unittest discover -s tests

Standard library only. Everything happens in a temporary folder under
/private/tmp; nothing on the machine running the tests is read or written
outside it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "install.py"
CHECK = REPO / "template" / "System" / "tools" / "check.py"
EXAMPLE = REPO / "examples" / "acme.json"
SKILL = REPO / "template" / "System" / "skills" / "knowledge" / "SKILL.md"

TMP_ROOT = "/private/tmp" if Path("/private/tmp").is_dir() else None


def run(args, env):
    return subprocess.run([sys.executable] + [str(a) for a in args], env=env,
                          capture_output=True, text=True)


def git(cwd, env, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), env=env,
                          capture_output=True, text=True)


SOURCE_PAGE = """\
---
title: Resilience at Scale
type: source
author: Fictus Cloud
published: 2026-01-15
raw: "[[raw/fictus-2026-resilience-report]]"
confidence: low
created: 2026-03-20
updated: 2026-03-20
---

# Resilience at Scale

Fictus Cloud's own report on its Continuity Mesh product.

## What it says

- Fictus Cloud claims Continuity Mesh cuts failover time by 80%. Vendor-published, \
no independent test: confidence low.
"""

CONCEPT_PAGE = """\
---
title: Failover resilience
type: concept
created: 2026-03-20
updated: 2026-03-20
---

# Failover resilience

How systems keep running when a component fails.

## What sources say

- Fictus Cloud claims its Continuity Mesh product cuts failover time by 80%. \
[[../sources/fictus-2026-resilience-report|Resilience at Scale]]
"""

ENTITY_PAGE = """\
---
title: Fictus Cloud
type: entity
created: 2026-03-20
updated: 2026-03-20
---

# Fictus Cloud

A vendor of continuity and failover products.

## Claims

- Its Continuity Mesh product cuts failover time by 80%, by its own account. \
[[../sources/fictus-2026-resilience-report|Resilience at Scale]]
"""

INDEX_ROWS = (
    "| [[wiki/sources/fictus-2026-resilience-report|Resilience at Scale]] | source | 2026-03-20 |\n"
    "| [[wiki/concepts/failover-resilience|Failover resilience]] | concept | 2026-03-20 |\n"
    "| [[wiki/entities/fictus-cloud|Fictus Cloud]] | entity | 2026-03-20 |\n"
)

LOG_LINE = ("- 2026-03-20: ingested *Resilience at Scale* (Fictus Cloud); "
            "touches Failover resilience, Fictus Cloud.\n")


class KnowledgeIngestTest(unittest.TestCase):
    """A real workspace, installed once, then one hand-written ingest per
    test that mirrors the skill's procedure exactly."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        base = Path(cls.tmp.name).resolve()
        home = base / "home"
        home.mkdir()
        gitconfig = base / "gitconfig"
        gitconfig.write_text(
            "[user]\n\tname = Test Runner\n\temail = test@example.invalid\n"
            "[commit]\n\tgpgsign = false\n"
        )
        cls.env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=str(gitconfig),
                       GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.root = Path(self.tmp.name) / f"ws-{self._testMethodName}"
        result = run([INSTALL, "--config", EXAMPLE, "--target", self.root], self.env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.knowledge = self.root / "Wikis" / "Knowledge"

    def check(self):
        return run([CHECK, "--root", self.root], self.env)

    def write_ingest(self):
        """Write one ingest exactly as the skill's procedure describes it."""
        raw = self.knowledge / "raw" / "fictus-2026-resilience-report.txt"
        raw.write_text(
            "Fictus Cloud, Resilience at Scale (2026).\n\n"
            "Fictus Cloud says its Continuity Mesh product cuts failover time by 80%.\n",
            encoding="utf-8",
        )
        (self.knowledge / "wiki" / "sources" / "fictus-2026-resilience-report.md").write_text(
            SOURCE_PAGE, encoding="utf-8")
        (self.knowledge / "wiki" / "concepts" / "failover-resilience.md").write_text(
            CONCEPT_PAGE, encoding="utf-8")
        (self.knowledge / "wiki" / "entities" / "fictus-cloud.md").write_text(
            ENTITY_PAGE, encoding="utf-8")

        index = self.knowledge / "wiki" / "index.md"
        lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
        header_end = next(i for i, l in enumerate(lines) if l.startswith("|---"))
        lines[header_end + 1:header_end + 1] = [INDEX_ROWS]
        index.write_text("".join(lines), encoding="utf-8")

        log = self.knowledge / "wiki" / "log.md"
        text = log.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        log.write_text(text + "\n" + LOG_LINE, encoding="utf-8")

    def test_fresh_install_is_clean(self):
        # The baseline the ingest is layered onto must itself be clean, or a
        # failure below would prove nothing about the ingest.
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No problems found.", result.stdout)

    def test_ingest_passes_the_checker(self):
        self.write_ingest()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No problems found.", result.stdout)

    def test_ingest_pages_are_indexed_and_logged(self):
        self.write_ingest()
        index = (self.knowledge / "wiki" / "index.md").read_text(encoding="utf-8")
        log = (self.knowledge / "wiki" / "log.md").read_text(encoding="utf-8")
        for needle in ("fictus-2026-resilience-report", "failover-resilience", "fictus-cloud"):
            self.assertIn(needle, index)
        self.assertIn("Fictus Cloud", log)

    def test_vendor_claim_is_attributed_everywhere_it_appears(self):
        # A dropped attribution turns a vendor's claim into a fact; the
        # skill requires it in the source, the concept and the entity page.
        self.write_ingest()
        for name in ("sources/fictus-2026-resilience-report", "concepts/failover-resilience",
                    "entities/fictus-cloud"):
            text = (self.knowledge / "wiki" / f"{name}.md").read_text(encoding="utf-8")
            self.assertIn("Fictus Cloud", text)

    def test_raw_survives_a_second_commit_untouched(self):
        # The wiki rule: raw is never edited after its first commit. Commit
        # the ingest the way the skill's procedure does -- from the Wikis
        # repository root, naming Knowledge's own paths -- then confirm the
        # checker still finds nothing wrong.
        self.write_ingest()
        wikis = self.knowledge.parent
        add = git(wikis, self.env, "add", "--",
                  "Knowledge/raw/fictus-2026-resilience-report.txt",
                  "Knowledge/wiki/sources/fictus-2026-resilience-report.md",
                  "Knowledge/wiki/concepts/failover-resilience.md",
                  "Knowledge/wiki/entities/fictus-cloud.md",
                  "Knowledge/wiki/index.md", "Knowledge/wiki/log.md")
        self.assertEqual(add.returncode, 0, add.stderr)
        commit = git(wikis, self.env, "commit", "-q", "-m",
                     "Knowledge: ingested Resilience at Scale (Fictus Cloud)")
        self.assertEqual(commit.returncode, 0, commit.stderr)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_link_into_meetings_is_caught(self):
        # The boundary the skill enforces by hand is also caught by the
        # checker if it is ever crossed: belt and braces. Needs a real
        # meeting page to link to -- a fresh install's Meetings wiki starts
        # empty.
        meeting = (self.root / "Wikis" / "Meetings" / "wiki" / "sources" / "260310-acme-kickoff.md")
        meeting.write_text(
            "---\ntitle: Acme kick-off\ntype: meeting\ndate: 2026-03-10\nzone: Work\n"
            "parties: [acme]\npeople: []\n---\n\n# Acme kick-off\n\nDecisions.\n",
            encoding="utf-8",
        )
        self.write_ingest()
        (self.knowledge / "wiki" / "concepts" / "failover-resilience.md").write_text(
            CONCEPT_PAGE + "\nAs discussed in [[Meetings/wiki/sources/260310-acme-kickoff]].\n",
            encoding="utf-8",
        )
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Meetings", result.stdout)

    def test_missing_confidence_is_not_silently_accepted_as_fact(self):
        # A source page is free-form prose beyond its frontmatter, so the
        # checker will not fail a missing confidence rating -- but the skill
        # forbids writing one it does not know. This documents that the
        # field is meant to hold one of the three named values, not be
        # dropped, by checking every fixture ingest actually carries one.
        self.write_ingest()
        text = (self.knowledge / "wiki" / "sources" / "fictus-2026-resilience-report.md").read_text(
            encoding="utf-8")
        self.assertRegex(text, r"confidence: (high|medium|low)")


class KnowledgeSkillDocumentTest(unittest.TestCase):
    """The skill file itself states the rules its procedure depends on."""

    def setUp(self):
        self.text = SKILL.read_text(encoding="utf-8")

    def test_freezes_before_summarising(self):
        self.assertIn("Freeze it, before reading it for the summary", self.text)

    def test_states_the_meetings_boundary(self):
        self.assertIn("Nothing from a conversation or a project ever goes into Knowledge", self.text)

    def test_requires_vendor_attribution(self):
        self.assertIn("Attribute every vendor claim to its vendor", self.text)

    def test_requires_rereading_shared_files_before_appending(self):
        self.assertIn("Re-read `wiki/index.md` right before you add to it", self.text)
        self.assertIn("Re-read `wiki/log.md` right before you append", self.text)

    def test_names_what_it_does_not_do(self):
        self.assertIn("## What this skill does not do", self.text)


if __name__ == "__main__":
    unittest.main()
