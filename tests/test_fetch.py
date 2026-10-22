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
from unittest import mock

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
    """Just enough of imaplib.IMAP4_SSL, or of imaplib.IMAP4 with STARTTLS: one mailbox, UIDs, flags and copies."""

    def __init__(self, messages, validity=b"7", password=PASSWORD, starttls_error=None):
        self.messages = dict(messages)  # uid -> bytes
        self.validity, self.password = validity, password
        self.flags, self.copies, self.calls = {}, [], []
        self.readonly = None
        self.logged_out = False
        self.contexts = []  # each SSL context handed over, on connecting or on STARTTLS
        self.starttls_error = starttls_error

    def __call__(self, host, port, ssl_context=None):  # used as the factory
        self.calls.append(("connect", host, port))
        if ssl_context is not None:
            self.contexts.append(ssl_context)
        return self

    def starttls(self, ssl_context=None):
        self.calls.append(("starttls",))
        if self.starttls_error:
            raise self.starttls_error
        self.contexts.append(ssl_context)
        return "OK", [b"Begin TLS negotiation now"]

    def shutdown(self):
        self.calls.append(("shutdown",))

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


class TestBridge(FetchCase):
    """A mailbox served by a bridge app on this machine: STARTTLS on its own port,
    and a certificate of its own to trust. Verification is never switched off."""

    def setUp(self):
        super().setUp()
        self.cafile = self.base / "config" / "bridge-cert.pem"
        self.cafile.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")  # read only by a fake context

    def test_implicit_tls_by_default_and_verified(self):
        server = FakeIMAP({3: message(3)})
        self.fetch(server)
        self.assertEqual(("connect", "imap.example.invalid", 993), server.calls[0])
        self.assertNotIn(("starttls",), server.calls)
        (context,) = server.contexts
        self.assertEqual(imap_fetch.ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)

    def test_starttls_upgrades_the_connection_before_login(self):
        self.write_config(server="127.0.0.1", port=1143, starttls=True)
        server = FakeIMAP({3: message(3)})
        self.assertEqual(1, len(self.fetch(server)))
        names = [c[0] for c in server.calls]
        self.assertEqual(["connect", "starttls", "login"], names[:3])
        self.assertEqual(("connect", "127.0.0.1", 1143), server.calls[0])
        (context,) = server.contexts  # the plain connection got none
        self.assertEqual(imap_fetch.ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)

    def test_starttls_port_defaults_to_143(self):
        self.write_config(starttls=True)
        self.assertEqual(143, imap_fetch.load_config(self.config_path)["port"])
        self.write_config()
        self.assertEqual(993, imap_fetch.load_config(self.config_path)["port"])

    def test_cafile_is_passed_to_the_ssl_context(self):
        self.write_config(server="127.0.0.1", port=1143, starttls=True, cafile=str(self.cafile))
        loaded = []

        class Context:
            verify_mode, check_hostname = imap_fetch.ssl.CERT_REQUIRED, True

            def load_verify_locations(self, cafile=None, capath=None, cadata=None):
                loaded.append(cafile)

        server = FakeIMAP({3: message(3)})
        with mock.patch.object(imap_fetch.ssl, "create_default_context", return_value=Context()) as made:
            self.fetch(server)
        made.assert_called_once_with()  # the default store, with nothing turned off
        self.assertEqual([str(self.cafile)], loaded)
        self.assertIsInstance(server.contexts[0], Context)

    def test_a_cafile_that_is_not_a_certificate_is_refused(self):
        self.write_config(cafile=str(self.cafile))
        with self.assertRaises(imap_fetch.FetchError) as caught:
            self.fetch(FakeIMAP({3: message(3)}))
        self.assertIn("PEM certificate", str(caught.exception))
        self.assertEqual([], self.waiting())

    def test_a_missing_cafile_is_refused(self):
        missing = self.base / "config" / "no-such-cert.pem"
        self.write_config(cafile=str(missing))
        with self.assertRaises(imap_fetch.FetchError) as caught:
            imap_fetch.load_config(self.config_path)
        self.assertIn("cafile", str(caught.exception))
        self.assertIn(str(missing), str(caught.exception))

    def test_no_option_turns_verification_off(self):
        for key in ("insecure", "verify", "ssl_verify", "check_hostname"):
            self.write_config(**{key: False})
            with self.assertRaises(imap_fetch.FetchError, msg=key):
                imap_fetch.load_config(self.config_path)

    def test_a_bridge_that_is_not_running_says_so(self):
        self.write_config(server="127.0.0.1", port=1143, starttls=True)

        def refused(host, port, ssl_context=None):
            raise ConnectionRefusedError(61, "Connection refused")

        with self.assertRaises(imap_fetch.FetchError) as caught:
            self.fetch(refused)
        self.assertIn("Could not reach the bridge at 127.0.0.1 port 1143", str(caught.exception))
        self.assertEqual([], self.waiting())

    def test_a_server_without_starttls_is_refused_before_login(self):
        self.write_config(server="127.0.0.1", port=1143, starttls=True)
        server = FakeIMAP({3: message(3)}, starttls_error=imap_fetch.imaplib.IMAP4.error(
            "STARTTLS extension not supported by server."))
        with self.assertRaises(imap_fetch.FetchError) as caught:
            self.fetch(server)
        self.assertIn("STARTTLS", str(caught.exception))
        self.assertNotIn("login", [c[0] for c in server.calls])

    def test_a_certificate_that_does_not_verify_names_cafile(self):
        self.write_config(server="127.0.0.1", port=1143, starttls=True)
        server = FakeIMAP({3: message(3)}, starttls_error=imap_fetch.ssl.SSLCertVerificationError(
            1, "certificate verify failed: self-signed certificate"))
        with self.assertRaises(imap_fetch.FetchError) as caught:
            self.fetch(server)
        self.assertIn('"cafile"', str(caught.exception))
        self.assertNotIn("login", [c[0] for c in server.calls])


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
