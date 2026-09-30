"""The optional IMAP fetcher, extras/fetch/imap_fetch.py, against a fake server.

    python3 -m unittest discover -s tests

No network: every test hands the fetcher a fake IMAP connection and a fake
Keychain. Invented names only.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from email.message import EmailMessage
from email import policy
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import build_workspace  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FETCH = REPO / "extras" / "fetch" / "imap_fetch.py"
INTAKE = REPO / "template" / "System" / "skills" / "intake" / "intake.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


imap_fetch = _load("garrick_imap_fetch", FETCH)
PASSWORD = "not-a-real-password"


def message(n, subject="Pallet forecast", msg_id=True):
    m = EmailMessage()
    m["From"] = "Dana Whitlock <dana.whitlock@acmecorp.example>"
    m["To"] = "Sam Rivera <sam@riveraadvisory.example>"
    m["Date"] = "Mon, 28 Sep 2026 09:%02d:00 +0200" % n
    m["Subject"] = subject
    if msg_id:
        m["Message-ID"] = "<%d@acmecorp.example>" % n
    m.set_content("Message %d.\n" % n)
    return m.as_bytes(policy=policy.default)


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL: one mailbox, UIDs, flags and copies."""

    def __init__(self, messages, validity=b"7", password=PASSWORD):
        self.messages = dict(messages)  # uid -> bytes
        self.validity, self.password = validity, password
        self.flags, self.copies, self.calls = {}, [], []
        self.readonly = None
        self.logged_out = False

    def __call__(self, host, port):  # used as the factory
        self.calls.append(("connect", host, port))
        return self

    def login(self, user, password):
        self.calls.append(("login", user))
        if password != self.password:
            raise imap_fetch.imaplib.IMAP4.error("LOGIN failed")
        return "OK", [b"logged in"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox))
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def response(self, code):
        return code, [self.validity]

    def uid(self, command, *args):
        self.calls.append(("uid", command) + args)
        if command == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self.messages)).encode()]
        if command == "FETCH":
            uid = int(args[0])
            assert args[1] == "(BODY.PEEK[])", args  # never sets \\Seen by itself
            return "OK", [(b"%d (UID %d BODY[] {%d}" % (uid, uid, len(self.messages[uid])), self.messages[uid]), b")"]
        if command == "STORE":
            self.flags.setdefault(int(args[0]), set()).add(args[2])
            return "OK", []
        if command == "COPY":
            self.copies.append((int(args[0]), args[1]))
            return "OK", []
        raise AssertionError(command)

    def logout(self):
        self.logged_out = True
        return "BYE", []


class FetchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()
        self.root = build_workspace(self.base / "Workspace")
        self.inbox = self.root / "Zones" / "Work" / "Inbox"
        self.config_path = self.base / "config" / "work-mail.json"
        self.write_config()

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, **extra):
        cfg = {"server": "imap.example.invalid", "user": "sam@riveraadvisory.example", "mailbox": "Garrick/Work",
               "inbox": str(self.inbox)}
        cfg.update(extra)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")

    def fetch(self, server, **kwargs):
        return imap_fetch.fetch(imap_fetch.load_config(self.config_path), imap_factory=server,
                                password=lambda: PASSWORD, log=lambda *_: None, **kwargs)

    def waiting(self):
        return sorted(p.name for p in self.inbox.iterdir() if not p.name.startswith("."))


class TestFetch(FetchCase):
    def test_saves_each_new_message_once(self):
        server = FakeIMAP({3: message(3), 5: message(5, "Freight Ledger Weekly")})
        saved = self.fetch(server)
        self.assertEqual(["260928-freight-ledger-weekly-5.eml", "260928-pallet-forecast-3.eml"], self.waiting())
        self.assertEqual(2, len(saved))
        self.assertEqual(message(3), (self.inbox / "260928-pallet-forecast-3.eml").read_bytes())
        self.assertTrue(server.readonly)  # nothing asked of the mailbox but reading
        self.assertEqual(({}, []), (server.flags, server.copies))
        self.assertTrue(server.logged_out)
        state = json.loads(self.config_path.with_suffix(".state.json").read_text())
        self.assertEqual([3, 5], state["Garrick/Work"]["uids"])

        server.messages[8] = message(8, "Seal kit quotes")
        self.assertEqual(["260928-seal-kit-quotes-8.eml"], [p.name for p in self.fetch(server)])
        self.assertEqual([], self.fetch(server))
        self.assertEqual(3, len(self.waiting()))

    def test_a_filed_message_is_not_fetched_again(self):
        server = FakeIMAP({3: message(3)})
        self.fetch(server)
        (self.inbox / "260928-pallet-forecast-3.eml").unlink()  # filed by the intake skill
        self.assertEqual([], self.fetch(server))

    def test_renumbered_mailbox_does_not_duplicate(self):
        self.fetch(FakeIMAP({3: message(3)}))
        again = self.fetch(FakeIMAP({1: message(3), 2: message(9)}, validity=b"8"))
        self.assertEqual(["260928-pallet-forecast-2.eml"], [p.name for p in again])

    def test_mark_read_and_copy_to(self):
        self.write_config(mark_read=True, copy_to="Garrick/Fetched")
        server = FakeIMAP({3: message(3), 4: message(4)})
        self.fetch(server)
        self.assertFalse(server.readonly)
        self.assertEqual({3: {"(\\Seen)"}, 4: {"(\\Seen)"}}, server.flags)
        self.assertEqual([(3, '"Garrick/Fetched"'), (4, '"Garrick/Fetched"')], server.copies)

    def test_decides_nothing(self):
        """Everything lands in the one Inbox the config names, whatever it says."""
        server = FakeIMAP({1: message(1), 2: message(2, "Newsletter"), 3: message(3, "Contract for Birch")})
        self.fetch(server)
        self.assertEqual(3, len(self.waiting()))
        for place in ("Wikis", "Zones/Personal", "Zones/Work/Acme Review", "Zones/Work/Birch Entry"):
            self.assertEqual([], [p for p in (self.root / place).rglob("*.eml")], place)
        intake = _load("garrick_intake_for_fetch", INTAKE)
        self.assertEqual(["mail"] * 3, [i["kind"] for i in intake.list_items(self.root)])

    def test_login_refused(self):
        with self.assertRaises(imap_fetch.FetchError):
            self.fetch(FakeIMAP({1: message(1)}, password="something else"))
        self.assertEqual([], self.waiting())


class TestPasswordAndConfig(FetchCase):
    def test_password_comes_from_the_keychain(self):
        seen = {}

        class Result:
            returncode, stdout = 0, PASSWORD + "\n"

        def run(args, **kwargs):
            seen["args"] = args
            return Result()

        self.assertEqual(PASSWORD, imap_fetch.keychain_password("garrick-imap", "sam@riveraadvisory.example", run=run))
        self.assertEqual(["security", "find-generic-password", "-s", "garrick-imap", "-a",
                          "sam@riveraadvisory.example", "-w"], seen["args"])

    def test_missing_keychain_entry(self):
        class Result:
            returncode, stdout = 44, ""

        with self.assertRaises(imap_fetch.FetchError) as caught:
            imap_fetch.keychain_password("garrick-imap", "sam@riveraadvisory.example", run=lambda *a, **k: Result())
        self.assertIn("security add-generic-password", str(caught.exception))

    def test_never_takes_a_password_from_the_config_or_an_argument(self):
        self.write_config(password=PASSWORD)
        with self.assertRaises(imap_fetch.FetchError) as caught:
            imap_fetch.load_config(self.config_path)
        self.assertNotIn(PASSWORD, str(caught.exception))
        err = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
            imap_fetch.main(["--config", str(self.config_path), "--password", PASSWORD])
        self.assertIn("unrecognized arguments", err.getvalue())

    def test_inbox_must_be_a_zone_inbox(self):
        for inbox in (self.root / "Wikis" / "Meetings" / "raw" / "inbox", self.root / "Zones" / "Work" / "Acme Review",
                      self.root / "Zones" / "Cedar" / "Inbox"):
            self.write_config(inbox=str(inbox))
            with self.assertRaises(imap_fetch.FetchError):
                imap_fetch.load_config(self.config_path)

    def test_unknown_and_missing_keys(self):
        self.write_config(folder="INBOX")
        with self.assertRaises(imap_fetch.FetchError):
            imap_fetch.load_config(self.config_path)
        self.config_path.write_text(json.dumps({"server": "imap.example.invalid"}))
        with self.assertRaises(imap_fetch.FetchError):
            imap_fetch.load_config(self.config_path)

    def test_not_installed_into_a_workspace(self):
        self.assertFalse((REPO / "template" / "extras").exists())
        self.assertEqual([], list((REPO / "template").rglob("imap_fetch.py")))


if __name__ == "__main__":
    unittest.main()
