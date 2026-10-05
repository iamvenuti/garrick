"""The inboxes, and the mechanics behind the intake skill.

    python3 -m unittest discover -s tests

Covers System/skills/intake/intake.py (list, parse, the three filing commands,
extract-attachment, learn), the mail parser in garrick_lib, and what check.py
does with what comes in: the walls on a mail page, a project's Sources/ that
came from mail, Knowledge pages with parties, and the rules for a zone's
Inbox. Also the guarantee that no command picks a destination on its own.
Invented parties only: Acme Corp (`acme`) and Birch & Co (`birch`), walled
from each other, as in fixtures.py.
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
from email import policy
from email.message import EmailMessage
from pathlib import Path

sys.dont_write_bytecode = True

from fixtures import GIT_ENV, HAVE_GIT, TOOLS, build_workspace, commit_all, git, write  # noqa: E402

import check  # noqa: E402  (fixtures puts the tools folder on sys.path)
import garrick_lib as lib  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INTAKE_PATH = REPO / "template" / "System" / "skills" / "intake" / "intake.py"


def _load_intake():
    spec = importlib.util.spec_from_file_location("garrick_intake", INTAKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = _load_intake()

# Wording only the Acme side ever wrote. It must never show up in a finding.
SECRET = "We will move every seal kit order to the Tilbury warehouse before the spring audit"


def eml(sender="Dana Whitlock <dana.whitlock@acmecorp.example>", to="Jo Example <jo@joexample.example>",
        cc=None, subject="Pallet forecast", date="Mon, 28 Sep 2026 09:12:00 +0200", plain=None, html=None,
        attachment=None, cte=None, headers=None) -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = to
    if cc:
        m["Cc"] = cc
    if date:
        m["Date"] = date
    m["Subject"] = subject
    for key, value in (headers or {}).items():
        m[key] = value
    if plain is not None:
        m.set_content(plain, cte=cte) if cte else m.set_content(plain)
        if html is not None:
            m.add_alternative(html, subtype="html")
    elif html is not None:
        m.set_content(html, subtype="html", cte=cte or "quoted-printable")
    if attachment:
        name, data = attachment
        m.add_attachment(data, maintype="text", subtype="csv", filename=name)
    return m.as_bytes(policy=policy.default)


class MailCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve() / "Workspace"
        build_workspace(self.root)
        self.work = self.root / "Zones" / "Work"
        self.inbox = self.work / "Inbox"
        self.meetings = self.root / "Wikis" / "Meetings"
        self.ctx = lib.load_context(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def drop(self, name, data, zone="Work"):
        path = self.root / "Zones" / zone / "Inbox" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path


# --------------------------------------------------------------------------- parsing


class TestParse(unittest.TestCase):
    def test_multipart_prefers_plain_and_lists_attachments(self):
        data = eml(plain="Plain words here.\n", html="<p>HTML words here.</p>",
                   attachment=("forecast.csv", b"quarter,pallets\nfirst,980\n"), cc="Owen Pike <owen.pike@acmecorp.example>")
        m = lib.parse_mail_bytes(data, ".eml")
        self.assertEqual("2026-09-28", m["date"])
        self.assertEqual("Pallet forecast", m["subject"])
        self.assertEqual([("Dana Whitlock", "dana.whitlock@acmecorp.example")], m["from"])
        self.assertEqual([("Owen Pike", "owen.pike@acmecorp.example")], m["cc"])
        self.assertIn("Plain words here.", m["body"])
        self.assertNotIn("HTML words", m["body"])
        self.assertEqual([{"name": "forecast.csv", "type": "text/csv", "bytes": 26}], m["attachments"])

    def test_plain_single_part(self):
        m = lib.parse_mail_bytes(eml(plain="Just text.\n"), ".eml")
        self.assertEqual("Just text.\n", m["body"])
        self.assertEqual([], m["attachments"])

    def test_html_only_is_stripped_to_text(self):
        html = ("<html><head><style>p {color: red}</style></head><body><p>First &amp; foremost.</p>"
                "<p>Second line<br>third line</p><script>alert(1)</script></body></html>")
        m = lib.parse_mail_bytes(eml(html=html), ".eml")
        self.assertIn("First & foremost.", m["body"])
        self.assertIn("Second line\nthird line", m["body"])
        self.assertNotIn("color", m["body"])
        self.assertNotIn("alert", m["body"])
        self.assertNotIn("<p>", m["body"])

    def test_base64_body_is_decoded(self):
        m = lib.parse_mail_bytes(eml(plain=SECRET + "\n", cte="base64"), ".eml")
        self.assertIn(SECRET, m["body"])

    def test_text_saved_by_a_mail_program(self):
        text = ("From: Theo Marsh <theo@birchco.example>\n"
                "Subject: Re: Launch timing\n"
                "Date: 28 September 2026 at 18:05:00 CEST\n"
                "To: Jo Example <jo@joexample.example>\n"
                "Cc: Iris Bell <iris.bell@birchco.example>,\n"
                " Owen Pike <owen.pike@acmecorp.example>\n"
                "\n"
                "The board said March.\n")
        m = lib.parse_mail_bytes(text.encode(), ".txt")
        self.assertEqual("2026-09-28", m["date"])
        self.assertEqual("Re: Launch timing", m["subject"])
        self.assertEqual(["iris.bell@birchco.example", "owen.pike@acmecorp.example"], [a for _, a in m["cc"]])
        self.assertEqual("The board said March.\n", m["body"])

    def test_markdown_with_frontmatter(self):
        text = ("---\nfrom: Theo Marsh <theo@birchco.example>\nto: jo@joexample.example\n"
                "date: 2026-09-27\nsubject: Board papers\n---\n\nPapers attached.\n")
        m = lib.parse_mail_bytes(text.encode(), ".md")
        self.assertEqual("2026-09-27", m["date"])
        self.assertEqual("Board papers", m["subject"])
        self.assertEqual([("Theo Marsh", "theo@birchco.example")], m["from"])
        self.assertEqual("Papers attached.\n", m["body"])

    def test_plain_note_without_headers(self):
        m = lib.parse_mail_bytes(b"Pasted from my phone.\n", ".txt")
        self.assertIsNone(m["date"])
        self.assertEqual([], m["from"])
        self.assertEqual("Pasted from my phone.\n", m["body"])

    def test_inline_forward_reveals_the_original_sender(self):
        body = ("See below.\n\n---------- Forwarded message ---------\n"
                "From: Dana Whitlock <dana.whitlock@acmecorp.example>\nDate: Mon, 28 Sep 2026\n"
                "Subject: Pallets\nTo: Jo <jo@gmail.com>\n\nThe forecast.\n")
        m = lib.parse_mail_bytes(eml(sender="Jo <jo@gmail.com>", to="jo+acme@gmail.com", plain=body), ".eml")
        self.assertIn(("Dana Whitlock", "dana.whitlock@acmecorp.example"), m["forwarded"])

    def test_dates_as_mail_programs_write_them(self):
        self.assertEqual("2026-09-28", lib.mail_date("Mon, 28 Sep 2026 09:12:00 +0200"))
        self.assertEqual("2026-09-28", lib.mail_date("Monday, September 28, 2026 9:12 AM"))
        self.assertEqual("2026-09-28", lib.mail_date("2026-09-28"))
        self.assertIsNone(lib.mail_date("next Tuesday"))


# --------------------------------------------------------------------------- parties


class TestPropose(MailCase):
    def propose(self, *addresses, zone="Work"):
        m = lib.parse_mail_bytes(b"", ".txt")
        m["from"] = [("", addresses[0])]
        m["to"] = [("", a) for a in addresses[1:]]
        return intake.suggest(self.ctx, zone, m)

    def test_domain_names_the_party(self):
        p = self.propose("dana.whitlock@acmecorp.example", "jo@joexample.example")
        self.assertEqual(["acme"], p["parties"])
        self.assertEqual([], p["ask"])
        self.assertEqual(["joexample.example"], p["unknown"])

    def test_subdomain_counts(self):
        p = self.propose("theo@mail.birchco.example", "jo@joexample.example")
        self.assertEqual(["birch"], p["parties"])
        p = self.propose("theo@eu.acmecorp.example")
        self.assertEqual(["acme"], p["parties"])

    def test_plus_tag_is_a_strong_hint_even_on_webmail(self):
        p = self.propose("jo@gmail.com", "jo+birch@gmail.com")
        self.assertEqual(["birch"], p["parties"])
        self.assertEqual([], p["ask"])

    def test_plus_tag_that_is_no_party_is_ignored(self):
        p = self.propose("dana.whitlock@acmecorp.example", "jo+work@gmail.com")
        self.assertEqual(["acme"], p["parties"])
        self.assertEqual([], p["ask"])

    def test_webmail_alone_never_names_a_party(self):
        p = self.propose("someone@gmail.com", "jo@joexample.example")
        self.assertEqual([], p["parties"])
        self.assertTrue(p["ask"])

    def test_webmail_listed_in_context_still_names_nobody(self):
        ctx = dict(self.ctx, parties={t: dict(e) for t, e in self.ctx["parties"].items()})
        ctx["parties"]["acme"]["domains"] = ["gmail.com"]
        self.assertEqual([], lib.parties_for_domain(ctx, "gmail.com"))

    def test_nothing_matches_asks(self):
        p = self.propose("pat@fernway.example")
        self.assertEqual([], p["parties"])
        self.assertIn("fernway.example", " ".join(p["ask"]))

    def test_ambiguous_domain_asks(self):
        self.ctx["parties"]["birch"]["domains"].append("shared.example")
        self.ctx["parties"]["acme"]["domains"].append("shared.example")
        p = self.propose("pat@shared.example")
        self.assertEqual([], p["parties"])
        self.assertIn("Acme Corp and Birch & Co", " ".join(p["ask"]))

    def test_walled_pair_asks_and_never_picks_a_side(self):
        p = self.propose("marta@cobalt.example", "owen.pike@acmecorp.example", "iris.bell@birchco.example")
        self.assertEqual(["acme", "birch"], p["parties"])
        self.assertEqual(1, len(p["ask"]))
        self.assertIn("wall", p["ask"][0])

    def test_party_from_another_zone_asks(self):
        p = self.propose("dana.whitlock@acmecorp.example", zone="Personal")
        self.assertEqual(["acme"], p["parties"])
        self.assertIn("Personal inbox", " ".join(p["ask"]))


# --------------------------------------------------------------------------- list and parse


def run_intake(root, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(INTAKE_PATH), "--root", str(root), *[str(a) for a in args]],
                          capture_output=True, text=True, env=env)


NEWSLETTER = dict(sender="The Freight Ledger <newsletter@freightledger.example>", subject="Freight Ledger Weekly",
                  plain="Winter surcharges arrive early this year, the weekly reports.\n",
                  headers={"List-Unsubscribe": "<mailto:leave@freightledger.example>"})


class TestListAndParse(MailCase):
    def test_parse_reports_zone_kind_parties_and_text(self):
        path = self.drop("forecast.eml", eml(plain="Only one quarter clears twelve hundred.\n",
                                             attachment=("forecast.csv", b"q,p\n")))
        info = intake.parse(self.root, path)
        self.assertEqual(("Work", "mail"), (info["zone"], info["kind"]))
        self.assertEqual("2026-09-28", info["date"])
        self.assertEqual("header", info["date_from"])
        self.assertEqual(["acme"], info["suggested"]["parties"])
        self.assertEqual([], info["suggested"]["ask"])
        self.assertFalse(info["suggested"]["sender_webmail"])
        self.assertFalse(info["mailing_list"])
        self.assertIn("twelve hundred", info["text"])
        self.assertEqual("forecast.csv", info["attachments"][0]["name"])

    def test_parse_flags_webmail_and_mailing_lists(self):
        info = intake.parse(self.root, self.drop("n.eml", eml(**NEWSLETTER)))
        self.assertTrue(info["mailing_list"])
        info = intake.parse(self.root, self.drop("w.eml", eml(sender="Pat <pat@gmail.com>", plain="x\n")))
        self.assertTrue(info["suggested"]["sender_webmail"])
        self.assertEqual([], info["suggested"]["parties"])

    def test_parse_falls_back_to_the_file_time(self):
        path = self.drop("note.txt", "From: dana.whitlock@acmecorp.example\n\nNo date on this one.\n")
        info = intake.parse(self.root, path)
        self.assertEqual(("mail", "file time"), (info["kind"], info["date_from"]))

    def test_parse_a_dropped_file(self):
        info = intake.parse(self.root, self.drop("Rates.csv", "lane,rate\nnorth,140\n"))
        self.assertEqual(("file", "Work"), (info["kind"], info["zone"]))
        self.assertIn("north,140", info["text"])
        info = intake.parse(self.root, self.drop("Contract.pdf", b"%PDF-1.4\0\0binary"))
        self.assertEqual(("file", None), (info["kind"], info["text"]))
        info = intake.parse(self.root, self.drop("call.m4a", b"\0\0"))
        self.assertEqual("unreadable", info["kind"])
        article = self.drop("Article.md", "# Lanes in winter\n\nPublished by a trade paper.\n")
        self.assertEqual("file", intake.parse(self.root, article)["kind"])

    def test_parse_refuses_a_file_outside_an_inbox(self):
        outside = write(self.work / "Acme Review" / "Sources" / "stray.eml", "From: a@acmecorp.example\n\nx\n")
        with self.assertRaises(intake.Refusal):
            intake.parse(self.root, outside)

    def test_nothing_parsed_names_a_destination(self):
        """Parsing says what an item is, never where it goes."""
        for name, data in (("m.eml", eml(plain="x\n", attachment=("a.csv", b"q,p\n"))), ("f.csv", "a,b\n")):
            info = intake.parse(self.root, self.drop(name, data))
            words = json.dumps(sorted(info)).lower()
            for word in ("destination", "project", "knowledge", "meetings", "sources", "route", "target"):
                self.assertNotIn(word, words)
        for item in intake.list_items(self.root):
            self.assertIn(item["kind"], intake.KINDS)
            self.assertEqual({"kind", "zone", "file", "date", "from", "subject"}, set(item))

    def test_list_puts_transcripts_first_then_mail_by_date_then_files(self):
        write(self.meetings / "raw" / "inbox" / "call.vtt", "WEBVTT\n")
        self.drop("later.eml", eml(plain="x\n", date="Mon, 28 Sep 2026 16:40:00 +0200"))
        self.drop("earlier.eml", eml(plain="x\n", date="Mon, 28 Sep 2026 09:12:00 +0200"))
        self.drop("home.txt", "Date: 2026-09-20\n\nx\n", zone="Personal")  # no sender: a file, not mail
        self.drop("letter.txt", "From: ray@larkandsons.example\nDate: 2026-09-21\n\nx\n", zone="Personal")
        self.drop("voice.m4a", b"\0")
        self.drop("Rates.pdf", b"%PDF")
        got = [(i["kind"], i["zone"], Path(i["file"]).name) for i in intake.list_items(self.root)]
        self.assertEqual([("transcript", "", "call.vtt"),
                          ("mail", "Personal", "letter.txt"), ("mail", "Work", "earlier.eml"),
                          ("mail", "Work", "later.eml"), ("file", "Personal", "home.txt"),
                          ("file", "Work", "Rates.pdf"), ("unreadable", "Work", "voice.m4a")], got)

    def test_cli_list_and_parse(self):
        self.drop("forecast.eml", eml(plain="Figures.\n"))
        r = run_intake(self.root, "list")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(["mail", "Work", "Zones/Work/Inbox/forecast.eml", "2026-09-28"], r.stdout.split("\t")[:4])
        r = run_intake(self.root, "list", "--json")
        self.assertEqual("mail", json.loads(r.stdout)[0]["kind"])
        r = run_intake(self.root, "parse", "--file", self.inbox / "forecast.eml")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(["acme"], json.loads(r.stdout)["suggested"]["parties"])
        self.assertFalse(list(INTAKE_PATH.parent.glob("__pycache__")))


# --------------------------------------------------------------------------- a conversation


class TestFileConversation(MailCase):
    def test_moves_the_raw_and_writes_the_page(self):
        data = eml(subject="Re: Fwd: Pallet forecast", plain="Figures inside.\n",
                   attachment=("forecast.csv", b"q,p\n"), cc="Owen Pike <owen.pike@acmecorp.example>")
        path = self.drop("forecast.eml", data)
        slug, raw, page = intake.file_conversation(self.root, path, ["acme"], today="2026-09-29")
        self.assertEqual("260928-pallet-forecast", slug)
        self.assertFalse(path.exists())
        self.assertEqual(self.meetings / "raw" / "260928-pallet-forecast.eml", raw)
        self.assertEqual(data, raw.read_bytes())
        fm = lib.parse_frontmatter(page)
        self.assertEqual("email", fm["type"])
        self.assertEqual("Work", fm["zone"])
        self.assertEqual(["acme"], fm["parties"])
        self.assertEqual("Pallet forecast", fm["title"])
        self.assertEqual("[[raw/260928-pallet-forecast]]", fm["raw"])
        self.assertEqual(["Owen Pike <owen.pike@acmecorp.example>"], fm["cc"])
        self.assertIn("forecast.csv", page.read_text())
        # The finished shape passes the meeting-page checks as it stands.
        found = [f for f in check.run_checks(self.root) if f.check in ("meetings", "inbox", "walls", "sources")]
        self.assertEqual([], [(f.check, f.message) for f in found])

    def test_never_overwrites(self):
        first = self.drop("a.eml", eml(plain="One.\n"))
        second = self.drop("b.eml", eml(plain="Two.\n"))
        s1, r1, _ = intake.file_conversation(self.root, first, ["acme"])
        s2, r2, _ = intake.file_conversation(self.root, second, ["acme"])
        self.assertNotEqual(s1, s2)
        self.assertIn("One.", r1.read_text())
        self.assertIn("Two.", r2.read_text())

    def test_refusals(self):
        path = self.drop("forecast.eml", eml(plain="x\n"))
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, path, [])  # the parties are never assumed
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, path, ["cedar"])
        undated = self.drop("undated.eml", eml(date=None, plain="x\n"))
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, undated, ["acme"])
        outside = write(self.work / "Acme Review" / "Sources" / "stray.eml", "From: a@acmecorp.example\n\nx\n")
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, outside, ["acme"])
        dropped = self.drop("Rates.csv", "lane,rate\n")
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, dropped, ["acme"])
        call = write(self.meetings / "raw" / "inbox" / "call.vtt", "WEBVTT\n")
        with self.assertRaises(intake.Refusal):
            intake.file_conversation(self.root, call, ["acme"])
        self.assertTrue(all(p.exists() for p in (path, undated, outside, dropped, call)))

    def test_cli(self):
        path = self.drop("forecast.eml", eml(plain="Figures.\n"))
        r = run_intake(self.root, "file-conversation", "--file", path, "--parties", "acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("260928-pallet-forecast", r.stdout.split("\t")[0])
        r = run_intake(self.root, "file-conversation", "--file", path, "--parties", "acme")
        self.assertEqual(1, r.returncode)
        self.assertEqual(1, len(r.stderr.strip().splitlines()))
        r = run_intake(self.root, "file-conversation", "--file", self.drop("b.eml", eml(plain="y\n")))
        self.assertEqual(2, r.returncode)  # --parties is required
        self.assertTrue((self.inbox / "b.eml").exists())


# --------------------------------------------------------------------------- something to read


class TestFileReading(MailCase):
    def test_a_newsletter_goes_to_knowledge_without_parties(self):
        data = eml(**NEWSLETTER)
        path = self.drop("weekly.eml", data)
        slug, raw, page = intake.file_reading(self.root, path, today="2026-09-29")
        self.assertEqual("freight-ledger-weekly", slug)
        self.assertEqual(self.root / "Wikis" / "Knowledge" / "raw" / "freight-ledger-weekly.eml", raw)
        frozen = raw.read_bytes()
        self.assertNotIn(b"jo@joexample.example", frozen.lower())
        self.assertIn(b"Freight Ledger Weekly", frozen)
        self.assertIn(b"newsletter@freightledger.example", frozen)
        self.assertFalse(path.exists())
        fm = lib.parse_frontmatter(page)
        self.assertEqual(("source", "The Freight Ledger", "2026-09-28"), (fm["type"], fm["author"], fm["published"]))
        self.assertNotIn("parties", fm)
        self.assertNotIn("zone", fm)
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check in ("knowledge", "inbox", "placeholders")])

    def test_a_newsletter_loses_every_trace_of_its_reader(self):
        data = eml(to="Jo Example <Jo@JoExample.example>", cc="jo.alias@joexample.example",
                   sender="The Freight Ledger <newsletter@freightledger.example>", subject="Freight Ledger Weekly",
                   plain="Sent to jo@joexample.example. Leave: https://fl.example/u?e=jo%40joexample.example\n",
                   html="<p>Sent to <a href='mailto:jo.alias@joexample.example'>you</a></p>",
                   attachment=("rates.csv", b"lane,rate\njo@joexample.example,1\n"),
                   headers={"Delivered-To": "jo@joexample.example",
                            "Received": "from mx.example by mx.joexample.example for <jo@joexample.example>"})
        _, raw, _ = intake.file_reading(self.root, self.drop("weekly.eml", data), today="2026-09-29")
        from email import policy
        from email.parser import BytesParser
        m = BytesParser(policy=policy.default).parsebytes(raw.read_bytes())
        for h in ("To", "Cc", "Delivered-To", "Received"):
            self.assertIsNone(m[h], h)
        texts = [p.get_content() for p in m.walk() if p.get_content_maintype() == "text" and not p.get_filename()]
        self.assertEqual(2, len(texts))
        for text in texts:
            self.assertNotIn("joexample", text.lower())
        self.assertIn("you%40removed.invalid", texts[0])
        attached = [p.get_content() for p in m.walk() if p.get_filename() == "rates.csv"]
        self.assertEqual(["lane,rate\njo@joexample.example,1\n"], attached)  # attachments are left as they are

    def test_a_dropped_article(self):
        path = self.drop("Lanes in winter.md", "# Lanes in winter\n\nA trade paper's view.\n")
        slug, raw, page = intake.file_reading(self.root, path, today="2026-09-29")
        self.assertEqual(("lanes-in-winter", ".md"), (slug, raw.suffix))
        self.assertIn("<who wrote or published it>", page.read_text())

    def test_refusals(self):
        first = self.drop("weekly.eml", eml(**NEWSLETTER))
        intake.file_reading(self.root, first)
        again = self.drop("weekly2.eml", eml(**NEWSLETTER))
        with self.assertRaises(intake.Refusal):
            intake.file_reading(self.root, again)  # the slug is taken: a word, never a number
        slug, _, _ = intake.file_reading(self.root, again, slug="freight-ledger-weekly-winter")
        self.assertEqual("freight-ledger-weekly-winter", slug)
        for name, data in (("call.m4a", b"\0"), ("call.vtt", "WEBVTT\n")):
            path = self.drop(name, data)
            with self.assertRaises(intake.Refusal):
                intake.file_reading(self.root, path)
            self.assertTrue(path.exists())

    def test_cli(self):
        path = self.drop("weekly.eml", eml(**NEWSLETTER))
        r = run_intake(self.root, "file-reading", "--file", path, "--title", "Winter surcharges")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("winter-surcharges\tWikis/Knowledge/raw/winter-surcharges.eml", "\t".join(r.stdout.split("\t")[:2]))


# --------------------------------------------------------------------------- material for a project


class TestFileToProject(MailCase):
    def test_moves_a_dropped_file_into_sources(self):
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        dest = intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        self.assertEqual(self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv", dest)
        self.assertFalse(path.exists())
        self.assertEqual([], [f for f in check.run_checks(self.root)])

    def test_never_without_an_explicit_project(self):
        path = self.drop("Rates.csv", "lane,rate\n")
        for project in (None, "", "  "):
            with self.assertRaises(intake.Refusal):
                intake.file_to_project(self.root, path, project, ["acme"])
        r = run_intake(self.root, "file-to-project", "--file", path, "--parties", "acme")
        self.assertEqual(2, r.returncode)
        self.assertIn("--project", r.stderr)
        self.assertTrue(path.exists())

    def test_refuses_a_walled_project_and_says_nothing_more(self):
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_to_project(self.root, path, "Zones/Work/Birch Entry", ["acme"])
        self.assertIn("wall", str(caught.exception))
        for word in ("acme", "birch", "seal"):
            self.assertNotIn(word, str(caught.exception).lower())
        self.assertTrue(path.exists())
        self.assertFalse((self.work / "Birch Entry" / "Sources").exists())

    def test_other_refusals(self):
        path = self.drop("Rates.csv", "lane,rate\n")
        for project, parties in (("Zones/Work/Acme Review", []), ("Zones/Work/Acme Review", ["cedar"]),
                                 ("Zones/Work/Inbox", ["acme"]), ("Zones/Work/Nowhere", ["acme"]),
                                 ("Wikis/Knowledge", ["acme"]), ("Zones/Work", ["acme"])):
            with self.assertRaises(intake.Refusal, msg=project):
                intake.file_to_project(self.root, path, project, parties)
        personal = write(self.root / "Zones" / "Personal" / "House" / "House.md",
                         "---\ntitle: House\ntype: project\nzone: Personal\nparty: acme\n---\n")
        with self.assertRaises(intake.Refusal):  # another zone: zones never mix
            intake.file_to_project(self.root, path, personal.parent, ["acme"])
        mail = self.drop("forecast.eml", eml(plain="x\n", attachment=("a.csv", b"q,p\n")))
        with self.assertRaises(intake.Refusal):  # a mail is a conversation first
            intake.file_to_project(self.root, mail, "Zones/Work/Acme Review", ["acme"])
        write(self.work / "Acme Review" / "Sources" / "Rates.csv", "older\n")
        with self.assertRaises(intake.Refusal):  # never overwrites
            intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        dest = intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"], name="Rates, September.csv")
        self.assertEqual("Rates, September.csv", dest.name)
        self.assertTrue(mail.exists())

    def test_cli(self):
        path = self.drop("Rates.csv", "lane,rate\n")
        r = run_intake(self.root, "file-to-project", "--file", path, "--project", "Zones/Work/Birch Entry",
                       "--parties", "acme")
        self.assertEqual(1, r.returncode)
        self.assertTrue(path.exists())
        r = run_intake(self.root, "file-to-project", "--file", path, "--project", "Zones/Work/Acme Review",
                       "--parties", "acme")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("Zones/Work/Acme Review/Sources/Rates.csv", r.stdout.strip())


QUOTES = b"maker,part,unit_price_eur\nKeld Seals,seal kit,4.10\nAnsel Gaskets,seal kit,3.85\n"


class TestExtractAttachment(MailCase):
    def filed(self, parties=("acme",), name="quotes.eml"):
        path = self.drop(name, eml(sender="Owen Pike <owen.pike@acmecorp.example>", subject="Seal kit quotes",
                                   plain="Both quotes attached.\n", attachment=("Seal kit quotes.csv", QUOTES)))
        slug, raw, _ = intake.file_conversation(self.root, path, list(parties))
        return slug, raw

    def test_saves_the_attachment_once_the_mail_is_recorded(self):
        slug, raw = self.filed()
        how, dest = intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", name="Seal kit quotes.csv")
        self.assertEqual(("saved", QUOTES), (how, dest.read_bytes()))
        self.assertTrue(raw.exists())  # the raw record keeps its own copy
        self.assertEqual("already", intake.extract_attachment(self.root, raw, "Zones/Work/Acme Review", index=1)[0])
        self.assertEqual([], [f for f in check.run_checks(self.root)])

    def test_refuses_a_mail_not_yet_recorded(self):
        path = self.drop("quotes.eml", eml(plain="x\n", attachment=("Seal kit quotes.csv", QUOTES)))
        with self.assertRaises(intake.Refusal):
            intake.extract_attachment(self.root, str(path), "Zones/Work/Acme Review", name="Seal kit quotes.csv")
        self.assertFalse((self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv").exists())

    def test_refuses_a_walled_project(self):
        slug, _ = self.filed()
        with self.assertRaises(intake.Refusal) as caught:
            intake.extract_attachment(self.root, slug, "Zones/Work/Birch Entry", name="Seal kit quotes.csv")
        self.assertNotIn("acme", str(caught.exception).lower())
        self.assertFalse((self.work / "Birch Entry" / "Sources").exists())
        slug, _ = self.filed(parties=("acme", "birch"), name="both.eml")
        for project in ("Zones/Work/Acme Review", "Zones/Work/Birch Entry"):  # both sides: neither project
            with self.assertRaises(intake.Refusal):
                intake.extract_attachment(self.root, slug, project, index=1)

    def test_other_refusals(self):
        slug, _ = self.filed()
        for kwargs in (dict(name="missing.csv"), dict(), dict(index=2)):
            with self.assertRaises(intake.Refusal):
                intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", **kwargs)
        with self.assertRaises(intake.Refusal):
            intake.extract_attachment(self.root, slug, None, index=1)
        write(self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv", "someone else's file\n")
        with self.assertRaises(intake.Refusal):
            intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", index=1)
        _, dest = intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", index=1, save_as="Quotes.csv")
        self.assertEqual("Quotes.csv", dest.name)

    def test_cli(self):
        slug, _ = self.filed()
        r = run_intake(self.root, "extract-attachment", "--mail", slug, "--name", "Seal kit quotes.csv")
        self.assertEqual(2, r.returncode)  # --project is required
        r = run_intake(self.root, "extract-attachment", "--mail", slug, "--project", "Zones/Work/Acme Review",
                       "--name", "Seal kit quotes.csv")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual("saved\tZones/Work/Acme Review/Sources/Seal kit quotes.csv", r.stdout.strip())


class TestNeverThroughALink(MailCase):
    """A filing command lands a file in the folder it checked, or nowhere: a
    symbolic link anywhere between the workspace and the destination, or a
    linked file in an inbox, is refused before anything moves."""

    def birch_sources(self):
        return {p.name for p in (self.work / "Birch Entry" / "Sources").iterdir()}

    def link(self, path, target):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), str(path))
        return path

    def setUp(self):
        super().setUp()
        write(self.work / "Birch Entry" / "Sources" / "Birch contacts.csv", "name\n")
        self.before = self.birch_sources()

    def assert_refused_cleanly(self, caught):
        message = str(caught.exception)
        self.assertIn("link", message)
        self.assertIn("Nothing was moved", message)
        self.assertNotIn("birch", message.lower())

    def test_a_linked_sources_folder(self):
        self.link(self.work / "Acme Review" / "Sources", self.work / "Birch Entry" / "Sources")
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        self.assert_refused_cleanly(caught)
        self.assertTrue(path.exists())
        self.assertEqual(self.before, self.birch_sources())
        r = run_intake(self.root, "file-to-project", "--file", path, "--project", "Zones/Work/Acme Review",
                       "--parties", "acme")
        self.assertEqual(1, r.returncode)
        self.assertTrue(path.exists())

    def test_a_linked_file_in_sources(self):
        dangling = self.work / "Birch Entry" / "Sources" / "Seal kit quotes.csv"
        self.link(self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv", dangling)
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        self.assert_refused_cleanly(caught)
        self.assertTrue(path.exists())
        self.assertFalse(dangling.exists())

    def test_a_linked_project_is_the_project_it_points_to(self):
        # The project folder itself is read where it really is, so the wall is
        # checked against the project the file would actually reach.
        self.link(self.work / "Acme Mirror", self.work / "Birch Entry")
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_to_project(self.root, path, "Zones/Work/Acme Mirror", ["acme"])
        self.assertIn("wall", str(caught.exception))
        self.assertTrue(path.exists())
        self.assertEqual(self.before, self.birch_sources())

    def test_an_attachment_into_a_linked_sources_folder(self):
        mail = self.drop("quotes.eml", eml(subject="Seal kit quotes", plain="Attached.\n",
                                           attachment=("Seal kit quotes.csv", QUOTES)))
        slug, raw, _ = intake.file_conversation(self.root, mail, ["acme"])
        self.link(self.work / "Acme Review" / "Sources", self.work / "Birch Entry" / "Sources")
        with self.assertRaises(intake.Refusal) as caught:
            intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", index=1)
        self.assert_refused_cleanly(caught)
        self.assertEqual(self.before, self.birch_sources())
        self.assertTrue(raw.exists())

    def test_an_attachment_onto_a_linked_file(self):
        mail = self.drop("quotes.eml", eml(subject="Seal kit quotes", plain="Attached.\n",
                                           attachment=("Seal kit quotes.csv", QUOTES)))
        slug, _, _ = intake.file_conversation(self.root, mail, ["acme"])
        dangling = self.work / "Birch Entry" / "Sources" / "Seal kit quotes.csv"
        self.link(self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv", dangling)
        with self.assertRaises(intake.Refusal) as caught:
            intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", index=1)
        self.assert_refused_cleanly(caught)
        self.assertFalse(dangling.exists())

    def test_a_conversation_into_a_linked_meetings_folder(self):
        for linked in (self.meetings / "raw", self.meetings / "wiki" / "sources"):
            with self.subTest(linked=linked.name):
                aside = linked.with_name(linked.name + "-aside")
                linked.rename(aside)
                os.symlink(str(self.work / "Birch Entry" / "Sources"), str(linked))
                path = self.drop("forecast.eml", eml(plain="Figures inside.\n"))
                with self.assertRaises(intake.Refusal) as caught:
                    intake.file_conversation(self.root, path, ["acme"])
                self.assert_refused_cleanly(caught)
                self.assertTrue(path.exists())
                self.assertEqual(self.before, self.birch_sources())
                linked.unlink()
                aside.rename(linked)

    def test_reading_into_a_linked_knowledge_folder(self):
        self.link(self.root / "Wikis" / "Knowledge" / "raw", self.work / "Birch Entry" / "Sources")
        path = self.drop("weekly.eml", eml(**NEWSLETTER))
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_reading(self.root, path)
        self.assert_refused_cleanly(caught)
        self.assertTrue(path.exists())
        self.assertEqual(self.before, self.birch_sources())

    def test_a_linked_file_in_an_inbox(self):
        outside = write(self.root / "Zones" / "Work" / "Inbox" / "real" / "Seal kit quotes.csv", "maker\n")
        path = self.link(self.inbox / "Seal kit quotes.csv", outside)
        with self.assertRaises(intake.Refusal) as caught:
            intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        self.assertIn("link", str(caught.exception))
        self.assertTrue(path.is_symlink())
        self.assertTrue(outside.exists())

    def test_ordinary_filing_still_works(self):
        path = self.drop("Seal kit quotes.csv", "maker,price\nKeld,4.10\n")
        dest = intake.file_to_project(self.root, path, "Zones/Work/Acme Review", ["acme"])
        self.assertEqual(self.work / "Acme Review" / "Sources" / "Seal kit quotes.csv", dest)
        self.assertEqual(self.before, self.birch_sources())


class TestLearn(MailCase):
    def test_adds_the_domain_and_the_next_mail_files_itself(self):
        path = self.drop("fernway.eml", eml(sender="Pat Rowe <pat@acmelabs.example>", plain="x\n"))
        self.assertTrue(intake.parse(self.root, path)["suggested"]["ask"])
        self.assertEqual("added", intake.learn(self.root, "acmelabs.example", "acme"))
        self.assertEqual("already", intake.learn(self.root, "@AcmeLabs.example", "acme"))
        self.assertEqual(["acmecorp.example", "acmelabs.example"],
                         lib.load_context(self.root)["parties"]["acme"]["domains"])
        again = intake.parse(self.root, path)["suggested"]
        self.assertEqual((["acme"], []), (again["parties"], again["ask"]))
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "context"])

    def test_adds_the_column_to_an_older_table(self):
        ctx = self.root / "System" / "context.md"
        text = ctx.read_text()
        text = text.replace("| Party | What it is | Zone | Tag | Domains |\n|---|---|---|---|---|",
                            "| Party | What it is | Zone | Tag |\n|---|---|---|---|")
        text = text.replace(" | acmecorp.example |", " |").replace(" | birchco.example, mail.birchco.example |", " |")
        ctx.write_text(text)
        self.assertEqual([], lib.load_context(self.root)["parties"]["birch"]["domains"])
        intake.learn(self.root, "birchco.example", "birch")
        self.assertIn("| Party | What it is | Zone | Tag | Domains |", ctx.read_text())
        self.assertIn("| Acme Corp | Client. Supply-chain review | Work | `acme` |  |", ctx.read_text())
        loaded = lib.load_context(self.root)["parties"]
        self.assertEqual((["birchco.example"], []), (loaded["birch"]["domains"], loaded["acme"]["domains"]))

    def test_refusals(self):
        with self.assertRaises(intake.Refusal):
            intake.learn(self.root, "gmail.com", "acme")
        with self.assertRaises(intake.Refusal):
            intake.learn(self.root, "birchco.example", "acme")  # already Birch's
        with self.assertRaises(intake.Refusal):
            intake.learn(self.root, "not a domain", "acme")
        with self.assertRaises(intake.Refusal):
            intake.learn(self.root, "cedar.example", "cedar")


# --------------------------------------------------------------------------- check.py


class TestWallsOnMail(MailCase):
    """A mail page is a meeting page to the walls: links, names and quotes."""

    def setUp(self):
        super().setUp()
        self.birch = self.work / "Birch Entry" / "Threads" / "Market Sizing"
        path = self.drop("tilbury.eml", eml(subject="Warehouse move", plain=SECRET + ".\n", cte="base64"))
        self.slug, _, _ = intake.file_conversation(self.root, path, ["acme"], today="2026-09-29")

    def walls(self):
        return [f for f in check.run_checks(self.root) if f.check == "walls"]

    def assertNoLeak(self, findings):
        text = check.report_text(findings, self.root) + check.report_ear(findings)
        for word in ("tilbury", "seal kit", "spring audit"):
            self.assertNotIn(word, text.lower())

    def test_clean(self):
        self.assertEqual([], self.walls())

    def test_link_across_the_wall(self):
        write(self.birch / "Notes.md", "See [[%s]].\n" % self.slug)
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn(self.slug, found[0].message)

    def test_quote_from_the_encoded_raw_mail(self):
        write(self.birch / "Notes.md", "Heard that they will move every seal kit order to the Tilbury warehouse "
                                       "before the spring audit.\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("repeats wording", found[0].message)
        self.assertNoLeak(found)

    def test_same_quote_on_the_near_side_is_fine(self):
        write(self.work / "Acme Review" / "Threads" / "Pricing" / "Notes.md", SECRET + ".\n")
        self.assertEqual([], self.walls())

    def test_a_party_domain_names_the_party(self):
        write(self.birch / "Notes.md", "Send it to procurement at acmecorp.example.\n")
        found = self.walls()
        self.assertEqual(1, len(found), found)
        self.assertIn("names Acme Corp", found[0].message)


class TestInboxChecks(MailCase):
    def findings(self, name):
        return [f for f in check.run_checks(self.root) if f.check == name]

    def test_inbox_is_not_a_project(self):
        self.drop("forecast.eml", eml(plain="x\n"))
        self.assertEqual([], [f for f in check.run_checks(self.root)])

    def test_zone_without_inbox_is_warned(self):
        (self.root / "Zones" / "Personal" / "Inbox" / ".gitkeep").unlink()
        (self.root / "Zones" / "Personal" / "Inbox").rmdir()
        found = self.findings("zones")
        self.assertEqual(["warning"], [f.severity for f in found])
        self.assertIn("Inbox", found[0].message)

    def test_audio_is_warned_and_any_other_file_is_welcome(self):
        self.drop("call.m4a", b"\0\0")
        self.drop("Contract.pdf", b"%PDF-1.4\0binary")
        self.drop("Rates.csv", "lane,rate\n")
        found = self.findings("inbox")
        self.assertEqual([("warning", "Zones/Work/Inbox/call.m4a")], [(f.severity, f.path) for f in found])

    def test_filed_to_knowledge_or_a_project_but_not_moved(self):
        data = eml(**NEWSLETTER)
        intake.file_reading(self.root, self.drop("weekly.eml", data))
        self.drop("weekly copy.eml", data)
        intake.file_to_project(self.root, self.drop("Rates.csv", "lane,rate\nnorth,140\n"),
                               "Zones/Work/Acme Review", ["acme"])
        self.drop("Rates copy.csv", "lane,rate\nnorth,140\n")
        found = self.findings("inbox")
        self.assertEqual(2, len(found), found)
        self.assertTrue(all("already filed" in f.message for f in found))

    def test_filed_but_not_moved(self):
        data = eml(plain="x\n")
        path = self.drop("forecast.eml", data)
        intake.file_conversation(self.root, path, ["acme"])
        self.drop("forecast copy.eml", data)
        found = self.findings("inbox")
        self.assertEqual(1, len(found), found)
        self.assertIn("already filed", found[0].message)

    def test_context_domain_rules(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| acmecorp.example |", "| acmecorp.example, gmail.com, birchco.example |"))
        messages = " ".join(f.message for f in self.findings("context"))
        self.assertIn("gmail.com", messages)
        self.assertIn("birchco.example is listed for acme and birch", messages)

    def real_repo(self, zone):
        shutil.rmtree(zone / ".git")
        git(zone, "init", "-q")
        lib.install_wall_hook(zone)
        commit_all(zone, "start")

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_committed_mail_is_an_error(self):
        self.real_repo(self.work)
        self.drop("forecast.eml", eml(plain="x\n"))
        commit_all(self.work, "oops")  # the fixture zone has no .gitignore, so the mail goes in
        found = self.findings("inbox")
        self.assertEqual(["error"], [f.severity for f in found])
        self.assertIn("history", found[0].message)

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_hook_refuses_staged_mail(self):
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py"):
            shutil.copy2(TOOLS / name, tools / name)
        self.real_repo(self.work)
        self.drop("forecast.eml", eml(plain="x\n"))
        git(self.work, "add", "-f", "Inbox/forecast.eml")
        res = subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "mail"], cwd=str(self.work),
                             env=dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode, res.stdout + res.stderr)
        lines = [l for l in res.stderr.splitlines() if l.strip()]
        self.assertEqual(1, len(lines), res.stderr)
        self.assertIn("Commit refused: Zones/Work/Inbox/forecast.eml", lines[0])

class TestSourcesFromMail(MailCase):
    """A file in a project's Sources/ that came from mail: the mail is filed in
    Meetings with its zone and parties, and those parties are not walled from
    the project's."""

    def setUp(self):
        super().setUp()
        self.acme_sources = self.work / "Acme Review" / "Sources"
        self.birch_sources = self.work / "Birch Entry" / "Sources"
        self.quotes = eml(sender="Owen Pike <owen.pike@acmecorp.example>", subject="Seal kit quotes",
                          plain="Both attached.\n", attachment=("Seal kit quotes.csv", QUOTES))

    def findings(self, *names):
        return [f for f in check.run_checks(self.root) if f.check in names]

    def test_extracted_attachment_is_clean(self):
        slug, _, _ = intake.file_conversation(self.root, self.drop("q.eml", self.quotes), ["acme"])
        intake.extract_attachment(self.root, slug, "Zones/Work/Acme Review", index=1)
        self.assertEqual([], self.findings("sources", "walls"))

    def test_attachment_saved_before_the_mail_was_filed(self):
        self.drop("q.eml", self.quotes)
        write(self.acme_sources / "Seal kit quotes.csv", QUOTES.decode())
        found = self.findings("sources")
        self.assertEqual(["error"], [f.severity for f in found])
        self.assertIn("not filed", found[0].ear)

    def test_attachment_of_a_mail_whose_page_is_unfinished(self):
        slug, _, page = intake.file_conversation(self.root, self.drop("q.eml", self.quotes), ["acme"])
        page.write_text(page.read_text().replace("parties: [acme]", "parties: []"))
        write(self.acme_sources / "Seal kit quotes.csv", QUOTES.decode())
        self.assertEqual(1, len(self.findings("sources")))

    def test_attachment_across_the_wall(self):
        slug, _, _ = intake.file_conversation(self.root, self.drop("q.eml", self.quotes), ["acme"])
        (self.birch_sources).mkdir(parents=True, exist_ok=True)
        (self.birch_sources / "numbers.csv").write_bytes(QUOTES)  # renamed, same bytes
        found = self.findings("walls", "sources")
        self.assertEqual([("walls", "error")], [(f.check, f.severity) for f in found])
        self.assertIn(slug, found[0].message)
        self.assertNotIn("Keld", check.report_text(found, self.root))

    def test_a_whole_mail_in_sources_needs_its_meetings_page(self):
        (self.acme_sources / "quotes.eml").write_bytes(self.quotes)
        self.assertEqual(1, len(self.findings("sources")))
        intake.file_conversation(self.root, self.drop("q.eml", self.quotes), ["acme"])
        self.assertEqual([], self.findings("sources", "walls"))

    def test_ordinary_sources_are_left_alone(self):
        write(self.acme_sources / "Supplier list.csv", "supplier,part\nKeld Seals,seal kit\n")
        write(self.acme_sources / "tiny.csv", "q,p\n")
        self.drop("forecast.eml", eml(plain="x\n", attachment=("tiny.csv", b"q,p\n")))  # too small to prove anything
        self.assertEqual([], self.findings("sources", "walls"))

    @unittest.skipUnless(HAVE_GIT, "git is not installed")
    def test_hook_refuses_a_walled_attachment(self):
        tools = self.root / "System" / "tools"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("check.py", "garrick_lib.py"):
            shutil.copy2(TOOLS / name, tools / name)
        shutil.rmtree(self.work / ".git")
        git(self.work, "init", "-q")
        lib.install_wall_hook(self.work)
        commit_all(self.work, "start")
        intake.file_conversation(self.root, self.drop("q.eml", self.quotes), ["acme"])
        self.birch_sources.mkdir(parents=True, exist_ok=True)
        (self.birch_sources / "numbers.csv").write_bytes(QUOTES)
        git(self.work, "add", "Birch Entry/Sources/numbers.csv")
        res = subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "numbers"], cwd=str(self.work),
                             env=dict(GIT_ENV, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True)
        self.assertNotEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("Commit refused: Zones/Work/Birch Entry/Sources/numbers.csv came from mail", res.stderr)


class TestKnowledgeCarriesNoParties(MailCase):
    def test_a_knowledge_page_with_parties_is_an_error(self):
        slug, _, page = intake.file_reading(self.root, self.drop("weekly.eml", eml(**NEWSLETTER)))
        self.assertEqual([], [f for f in check.run_checks(self.root) if f.check == "knowledge"])
        page.write_text(page.read_text().replace("type: source", "type: source\nparties: [acme]\nzone: Work"))
        found = [f for f in check.run_checks(self.root) if f.check == "knowledge"]
        self.assertEqual(["error"], [f.severity for f in found])
        self.assertIn("`parties` and `zone`", found[0].message)


if __name__ == "__main__":
    unittest.main()
