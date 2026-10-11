"""An address kept for reading, filed into Knowledge: the fetcher's
"reading" flag, intake.py's skip, and the reading sweep in the jobs extra.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

from fixtures import HAVE_GIT, build_workspace, git, write  # noqa: E402
from test_intake import NEWSLETTER, eml  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "template" / "System"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadingCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        for rel in ("skills/intake/intake.py", "skills/meetings/ingest.py", "tools/garrick_lib.py"):
            (self.root / "System" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(TEMPLATE / rel, self.root / "System" / rel)
        self.inbox = self.root / "Zones" / "Work" / "Inbox"
        self.intake = _load("garrick_intake_reading", self.root / "System" / "skills" / "intake" / "intake.py")

    def drop(self, name, data):
        path = self.inbox / name
        path.write_bytes(data)
        return path


class TestSkip(ReadingCase):
    def test_a_thin_item_leaves_the_inbox_with_its_reason_logged(self):
        path = self.drop("reading-260928-sale-1.eml", eml(sender="Shop <deals@shop.example>", subject="50% off",
                                                          plain="Sale.\n"))
        items = self.intake.list_items(self.root)
        self.assertEqual("reading", next(i for i in items if i["file"].endswith(path.name))["route"])
        said = self.intake.skip(self.root, path, "thin: a promotion", today="2026-10-12")
        self.assertIn("50% off", said)
        self.assertFalse(path.exists())
        log = (self.inbox / ".skipped.log").read_text()
        self.assertIn("2026-10-12\treading-260928-sale-1.eml\tShop <deals@shop.example>\t50% off\tthin: a promotion", log)
        self.assertNotIn(".skipped.log", [i["file"] for i in self.intake.list_items(self.root)])

    def test_never_a_transcript_and_never_without_a_reason(self):
        t = self.root / "Wikis" / "Meetings" / "raw" / "inbox" / "call.txt"
        write(t, "Dana: Monday.\n")
        with self.assertRaises(self.intake.Refusal):
            self.intake.skip(self.root, t, "thin")
        path = self.drop("note.eml", eml(plain="x\n"))
        with self.assertRaises(self.intake.Refusal):
            self.intake.skip(self.root, path, "  ")
        self.assertTrue(t.exists() and path.exists())


class TestFetcherReading(unittest.TestCase):
    def test_a_reading_mailbox_is_saved_with_the_mark(self):
        fetch = _load("garrick_imap_reading", REPO / "extras" / "fetch" / "imap_fetch.py")
        self.assertIn("reading", fetch.KNOWN)
        self.assertFalse(fetch.DEFAULTS["reading"])
        self.assertIn('(READING_PREFIX if cfg.get("reading") else "") + file_name(message, uid)',
                      (REPO / "extras" / "fetch" / "imap_fetch.py").read_text())
        self.assertEqual(fetch.READING_PREFIX, self_prefix())


def self_prefix():
    return _load("garrick_intake_prefix", TEMPLATE / "skills" / "intake" / "intake.py").READING_PREFIX


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class TestReadingSweep(ReadingCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                                           "GIT_AUTHOR_NAME": "Jo", "GIT_AUTHOR_EMAIL": "jo@example.invalid",
                                           "GIT_COMMITTER_NAME": "Jo", "GIT_COMMITTER_EMAIL": "jo@example.invalid",
                                           "GARRICK_JOBS_DIR": str(Path(self._tmp.name) / "jobs")})
        env.start()
        self.addCleanup(env.stop)
        wikis = self.root / "Wikis"
        shutil.rmtree(wikis / ".git", ignore_errors=True)
        git(wikis, "init", "-q")
        git(wikis, "add", "-A")
        git(wikis, "commit", "-q", "-m", "start")
        self.wikis = wikis
        sys.path.insert(0, str(REPO / "extras" / "jobs"))
        self.job = _load("garrick_reading_sweep", REPO / "extras" / "jobs" / "reading_sweep.py")

    def test_it_files_the_reading_and_leaves_a_partys_mail_for_you(self):
        self.drop("reading-260928-freight-ledger-weekly-1.eml", eml(**NEWSLETTER))
        self.drop("reading-260928-pallet-forecast-2.eml", eml(plain="Our figures.\n"))       # from acmecorp.example
        self.drop("260928-other-3.eml", eml(plain="Not from the reading address.\n"))
        prompts = []

        def run(tier, prompt, allow=(), cwd=None, **kw):
            prompts.append((prompt, list(allow)))
            for line in prompt.splitlines():
                if line.startswith("- Zones/"):
                    subprocess.run([sys.executable, str(self.root / "System" / "skills" / "intake" / "intake.py"),
                                    "--root", str(self.root), "file-reading", "--file", str(self.root / line[2:])],
                                   check=True, capture_output=True)
            return 0, "Filed it.\nFILED 1 SKIPPED 0\n" + self.job.SENTINEL + "\n"
        out = []
        with mock.patch.object(self.job.agent, "run", side_effect=run), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
            code = self.job.main(["--workspace", str(self.root), "--zone", "Work"])
        self.assertEqual(0, code, out)
        [(prompt, allow)] = prompts
        self.assertIn("reading-260928-freight-ledger-weekly-1.eml", prompt)
        self.assertNotIn("pallet-forecast", prompt)                                  # a party's domain: never unattended
        self.assertNotIn("other-3", prompt)                                          # not marked for reading
        self.assertIn("Bash(python3 System/skills/intake/intake.py:*)", allow)
        self.assertTrue(any("left for you" in line and "pallet-forecast" in line for line in out), out)
        self.assertTrue((self.inbox / "reading-260928-pallet-forecast-2.eml").exists())
        self.assertIn("Knowledge: reading swept; 1 filed, 0 skipped", git(self.wikis, "log", "-1", "--format=%s"))
        self.assertIn("Knowledge/raw/freight-ledger-weekly.eml", git(self.wikis, "show", "--stat", "--format=", "HEAD"))

    def test_an_incomplete_answer_commits_nothing(self):
        self.drop("reading-260928-freight-ledger-weekly-1.eml", eml(**NEWSLETTER))
        with mock.patch.object(self.job.agent, "run", return_value=(0, "I stopped.")), mock.patch("builtins.print"):
            self.assertEqual(self.job.EXIT_INCOMPLETE, self.job.main(["--workspace", str(self.root), "--zone", "Work"]))
        self.assertEqual("start", git(self.wikis, "log", "-1", "--format=%s").strip())


if __name__ == "__main__":
    unittest.main()
