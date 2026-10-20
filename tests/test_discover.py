"""System/tools/discover.py: find the pieces of work in a folder you already keep, read-only (#182).

    python3 -m unittest discover -s tests -p test_discover.py

Builds its folders in a temporary folder: the worked example's drive, a
corporate cloud-drive tree, a flat dump and an employer drive, as the stage 2
trial had them, plus a folder of weekly status reports beside real work and a
folder of old work that scores alike. Every name is invented, and every date is
counted back from the day the test chooses. Each folder is compared before and
after every command, byte for byte, with its sizes, dates and folders.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "template" / "System" / "tools"
TOOL = TOOLS / "discover.py"
BUILD = REPO / "examples" / "example-work" / "build.py"
_spec = importlib.util.spec_from_file_location("garrick_discover", str(TOOL))
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

TODAY = datetime.datetime(2026, 10, 17, 18, 0)          # when the fixtures were last touched
AS_OF = "2026-10-17"                                    # and the day discovery scores them on
SCORED = datetime.datetime(2026, 10, 17, 23, 59)
EXAMPLE_DAY = datetime.date(2026, 10, 20)               # the example's drive, built on a Tuesday
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
UNSAID = re.compile(r"\b(zones?|projects?|threads?|repositor(y|ies)|commits?|git)\b", re.I)


# ---------------------------------------------------------------- the trial's fixtures, ported

class Maker:
    """Writes files with explicit modification times, counted back from TODAY, with the trial's random draws."""

    def __init__(self, seed: int = 17):
        self.rnd = random.Random(seed)

    def put(self, root, rel, days, size=None):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"synthetic " + rel.encode() + b"\n" * (size or self.rnd.randint(1, 40)))
        t = (TODAY - datetime.timedelta(days=days, hours=self.rnd.randint(0, 9),
                                        minutes=self.rnd.randint(0, 59))).timestamp()
        os.utime(p, (t, t))

    def spread(self, lo, hi, n):
        return [self.rnd.randint(lo, hi) for _ in range(n)]

    def corporate(self, root):
        put, spread, rnd = self.put, self.spread, self.rnd
        C = "Clients"
        g = f"{C}/Brightwater Energy/Grid audit 2026"
        for name, d in [("Grid audit report.docx", 1), ("Substation data.xlsx", 2), ("Site visit notes.docx", 4),
                        ("Findings summary.pptx", 3), ("Interview list.xlsx", 6)]:
            put(root, f"{g}/Working/{name}", d)
        put(root, f"{g}/Working/~$id audit report.docx", 1, 1)
        for name, d in [("Grid audit report v0.3.docx", 5), ("Findings summary v1.pptx", 9), ("Proposal.docx", 30)]:
            put(root, f"{g}/Draft/{name}", d)
        put(root, f"{g}/Final/Proposal signed.pdf", 28)
        put(root, f"{C}/Brightwater Energy/Brightwater NDA.pdf", 500)
        put(root, f"{C}/Brightwater Energy/Brightwater contacts.xlsx", 60)
        put(root, f"{C}/Brightwater Energy/Proposal.docx", 400)

        h = f"{C}/Halvorsen Logistics/Warehouse rollout"
        for name, d in [("Rollout plan.xlsx", 4), ("Site list.xlsx", 7), ("Steering committee 2026-10-09.pptx", 8)]:
            put(root, f"{h}/Working/{name}", d)
        for name, d in [("Rollout plan v2.docx", 10), ("Training approach.docx", 13)]:
            put(root, f"{h}/Working/Draft/{name}", d)
        for name, d in [("Rollout plan.docx", 21), ("Final report.docx", 25), ("Final report (1).docx", 25)]:
            put(root, f"{h}/Working/Draft/Final/{name}", d)
        put(root, f"{h}/Working/Draft/Final/~$nal report.docx", 25, 1)
        for i, d in enumerate(spread(300, 340, 6)):
            put(root, f"{C}/Halvorsen Logistics/Contract renewal 2025/Renewal doc {i + 1}.docx", d)
        put(root, f"{C}/Halvorsen Logistics/Proposal.docx", 410)

        o = f"{C}/Ostrava Foods/Market entry study"
        for name, d in [("Competitor scan.xlsx", 11), ("Retailer interviews.docx", 15), ("Market sizing.xlsx", 18),
                        ("Desk research sources.docx", 30)]:
            put(root, f"{o}/Research/{name}", d)
        for name, d in [("Entry options.pptx", 12), ("Executive summary.docx", 16)]:
            put(root, f"{o}/Working/{name}", d)
        put(root, f"{o}/Working/Draft/Executive summary v1.docx", 22)

        for name, d in [("Venue shortlist.xlsx", 8), ("Agenda draft.docx", 9), ("Budget.xlsx", 12),
                        ("Travel bookings.xlsx", 14), ("Session ideas.docx", 20), ("Invite.docx", 25),
                        ("Dietary requirements.xlsx", 10)]:
            put(root, f"Internal/Team offsite 2026/{name}", d)
        for name, d in [("Job description analyst.docx", 35), ("Interview scorecard.xlsx", 14),
                        ("CV Imogen Varga.pdf", 16), ("CV Tobias Lindqvist.pdf", 17), ("CV Priya Kanthan.pdf", 19),
                        ("Shortlist.xlsx", 15)]:
            put(root, f"Internal/Hiring - analyst role/{name}", d)
        for name, d in [("Budget 2026 model.xlsx", 19), ("Headcount plan.xlsx", 24), ("Budget assumptions.docx", 30),
                        ("Budget 2026 board slides.pptx", 22), ("Cost centre mapping.xlsx", 50)]:
            put(root, f"2025/Budget 2026 planning/{name}", d)

        for i, d in enumerate(spread(200, 420, 7)):
            put(root, f"{C}/Pellham Bank/Onboarding/Onboarding pack part {i + 1}.docx", d)
        put(root, f"{C}/Pellham Bank/Onboarding/Proposal.docx", 430)
        for q in ["Q1 Board pack", "Q2 Board pack", "Q3 Board pack", "Q4 Board pack"]:
            for i, d in enumerate(spread(290, 650, 9)):
                put(root, f"2024/{q}/Board paper {i + 1}.docx", d)
        for i, d in enumerate(spread(290, 650, 12)):
            put(root, f"2024/Expenses/Expense claim {i + 1}.pdf", d)
        for i, d in enumerate(spread(290, 650, 12)):
            put(root, f"2024/Meeting notes {i + 1}.docx", d)
        for i, d in enumerate(spread(60, 360, 14)):
            put(root, f"2025/Board packs/Board paper 2025-{i + 1}.docx", d)
        for i, d in enumerate(spread(150, 200, 8)):
            put(root, f"2025/Strategy day/Strategy day material {i + 1}.pptx", d)
        for i, d in enumerate(spread(70, 360, 10)):
            put(root, f"2025/Expenses/Expense claim 2025-{i + 1}.pdf", d)

        for i, name in enumerate(["Proposal template.docx", "Invoice template.xlsx", "Slide master.potx",
                                  "Letterhead.dotx", "Report template.docx", "SOW template.docx", "NDA template.docx",
                                  "Timesheet.xlsx", "Status report template.docx", "Kickoff deck template.pptx",
                                  "Risk register.xlsx", "RACI template.xlsx", "Meeting minutes template.docx",
                                  "Expense form.xlsx", "Org chart.pptx"]):
            put(root, f"Templates/{name}", 3 if i == 0 else rnd.randint(100, 700))
        for i, d in enumerate(spread(400, 1200, 48)):
            put(root, f"Archive/Old clients/Client file {i + 1}.docx", d)
        put(root, "Archive/Moved from laptop/Proposal.docx", 2)
        put(root, "Archive/Moved from laptop/Rate card.xlsx", 2)
        for name, d in [("Tax return 2025.pdf", 5), ("Payslip September.pdf", 5), ("Mortgage offer.pdf", 40),
                        ("Car insurance.pdf", 90), ("Gym membership.pdf", 200), ("Passport scan.pdf", 300),
                        ("Holiday ideas.docx", 25), ("Payslip August.pdf", 35), ("Payslip July.pdf", 66),
                        ("Kids school forms.pdf", 45), ("Pension statement.pdf", 120), ("Recipes.docx", 400)]:
            put(root, f"Personal/{name}", d)
        for i, d in enumerate(spread(0, 10, 12)):
            put(root, f"Desktop/Screenshot 2026-10-{17 - d:02d} at 1{i % 10}.0{i % 6}.12.png", d)
        for name, d in [("Untitled.docx", 0), ("Document1.docx", 1), ("notes.txt", 2), ("todo.txt", 1),
                        ("Book1.xlsx", 3), ("Copy of Rollout plan.xlsx", 4), ("print this.pdf", 6), ("logo.png", 9)]:
            put(root, f"Desktop/{name}", d)
        for i, d in enumerate(spread(0, 60, 25)):
            put(root, f"Microsoft Teams Chat Files/{rnd.choice(['image', 'Book', 'Presentation', 'export', 'file'])}"
                      f" ({i}).{rnd.choice(['png', 'xlsx', 'pptx', 'pdf'])}", d)
        for i, d in enumerate([2, 9, 16, 23, 30, 40]):
            put(root, f"Recordings/Meeting in General-2026{10 if d < 17 else 9:02d}{(17 - d) % 28 + 1:02d}"
                      f"_120000-Meeting Recording.mp4", d)
        for name, d in [("Expenses October.xlsx", 6), ("Document1.docx", 12), ("Proposal.docx", 33),
                        ("Final report.docx", 80)]:
            put(root, name, d)
        for dirpath, dirnames, _ in list(os.walk(root)):
            put(root, os.path.relpath(os.path.join(dirpath, ".DS_Store"), root), 0, 1)
        put(root, "desktop.ini", 0, 1)
        put(root, "Clients/Ostrava Foods/~$try options.pptx", 12, 1)

    def flat(self, root):
        rnd = self.rnd
        F = []

        def add(name, d):
            F.append((name, d))

        for name, d in [("Kestrel onboarding checklist.xlsx", 3), ("Kestrel kickoff 2026-10-06 notes.docx", 11),
                        ("Kestrel SOW signed.pdf", 12), ("Kestrel org chart.pptx", 9),
                        ("Kestrel data migration plan v2.docx", 6), ("Kestrel data migration plan v3.docx", 2),
                        ("2026-10-14 Kestrel weekly.docx", 3), ("Kestrel invoice 1.pdf", 5),
                        ("Onboarding timeline.xlsx", 4)]:
            add(name, d)
        for name, d in [("Pitch deck v1.pptx", 30), ("Pitch deck v2.pptx", 24), ("Pitch deck v3.pptx", 18),
                        ("Pitch deck v4 FINAL.pptx", 10), ("Pitch deck v4 FINAL (2).pptx", 9),
                        ("Pitch deck v5 FINAL really.pptx", 5), ("~$tch deck v5 FINAL really.pptx", 5)]:
            add(name, d)
        for name, d in [("2026-09-28 Q3 review notes.docx", 19), ("Q3 review slides.pptx", 20),
                        ("Q3 review numbers.xlsx", 22), ("Q3 review actions.docx", 18), ("Q3 forecast.xlsx", 25),
                        ("2025-09-12 Q3 review notes.docx", 400), ("Q3 review slides 2025.pptx", 401),
                        ("Q3 review numbers 2025.xlsx", 402), ("Q3 actions 2025.docx", 399)]:
            add(name, d)
        for name, d in [("Marlow tender RFP.pdf", 18), ("Marlow tender response draft.docx", 8),
                        ("Marlow tender pricing.xlsx", 6), ("Marlow Q&A clarifications.docx", 4),
                        ("Marlow tender response v2.docx", 3), ("Marlow references.docx", 7)]:
            add(name, d)
        for name, d in [("Office move floorplan.pdf", 45), ("Office move quotes.xlsx", 52), ("Moving checklist.docx", 60)]:
            add(name, d)
        for name, d in [("Annual report 2025 draft.docx", 230), ("Annual report 2025 final.pdf", 200),
                        ("Annual report photos.zip", 240), ("Annual report 2025 comments.docx", 225),
                        ("Annual report design brief.docx", 250)]:
            add(name, d)
        for wk in range(20, 42):
            add(f"Weekly report 2026-W{wk:02d}.docx", (42 - wk) * 7 + 1)
        for i in range(22):
            d = rnd.randint(0, 15)
            add(f"Screenshot 2026-10-{max(1, 17 - d):02d} at {rnd.randint(8, 18)}.{rnd.randint(10, 59)}.{i + 10}.png", d)
        for i in range(10):
            add(f"IMG_{2040 + i}.jpg", rnd.randint(0, 90))
        for i in range(12):
            add(f"Invoice {4460 + i}.pdf", rnd.randint(0, 330))
        for i in range(6):
            add(f"Scan 2026-0{3 + i}-0{i + 1}.pdf", 200 - i * 30)
        for name, d in [("Document1.docx", 1), ("Document2.docx", 14), ("untitled.txt", 2), ("Book1.xlsx", 7),
                        ("Presentation1.pptx", 20)]:
            add(name, d)
        for name, d in [("Train tickets Lyon.pdf", 16), ("Parking permit.pdf", 70), ("Holiday rota 2026.xlsx", 33),
                        ("CV Tamsin Orr.pdf", 27), ("Expenses September.xlsx", 15), ("Team photo.jpg", 100),
                        ("Org chart.pptx", 130), ("Pricing ideas.docx", 13), ("Notes from call.docx", 5),
                        ("Meeting notes.docx", 8), ("Ideas.txt", 1), ("Contract.pdf", 40), ("Proposal.docx", 26),
                        ("Proposal (1).docx", 26), ("Agenda.docx", 10), ("Feedback form.pdf", 55),
                        ("Insurance certificate.pdf", 180), ("Board minutes June.docx", 120), ("Market map.pptx", 66),
                        ("Budget.xlsx", 21), ("Draft.docx", 3), ("Final.docx", 9), ("Reading list.docx", 150),
                        ("LinkedIn post ideas.docx", 12), ("Price list 2026.pdf", 280)]:
            add(name, d)
        for name, d in [("Supplier review 2025 scorecard.xlsx", 380), ("Supplier review 2025 summary.docx", 370),
                        ("Supplier review shortlist.xlsx", 390), ("Supplier review interviews.docx", 375),
                        ("Supplier review 2025.pptx", 365)]:
            add(name, d)
        for name, d in [("Brand refresh moodboard.pdf", 150), ("Brand refresh brief.docx", 140),
                        ("Brand refresh agency quotes.xlsx", 135), ("Brand refresh v2 concepts.pdf", 125),
                        ("Brand refresh feedback.docx", 122), ("New logo options.pdf", 128)]:
            add(name, d)
        add(".DS_Store", 0)
        for name, d in F:
            self.put(root, name, d)

    def quillfield(self, root):
        put, spread, rnd = self.put, self.spread, self.rnd
        M = "Marketing"
        c = f"{M}/Catalogue 2027"
        for name, d in [("Catalogue 2027 page plan.xlsx", 1), ("Page count note.docx", 2), ("Cover options.pptx", 3),
                        ("Product copy - Office.docx", 5), ("Catalogue 2027 schedule.xlsx", 6),
                        ("Product copy - Lounge.docx", 8), ("Brindlecote Print quote.pdf", 9),
                        ("Product copy - Meeting rooms.docx", 10), ("Photo list.xlsx", 12), ("Paper samples.pdf", 15),
                        ("Dealer feedback on 2026.xlsx", 20), ("Catalogue 2026 feedback.docx", 28)]:
            put(root, f"{c}/{name}", d)
        put(root, f"{c}/~$talogue 2027 page plan.xlsx", 1, 1)
        for name, d in [("Lounge spread copy.docx", 1), ("Price pages draft.xlsx", 2), ("Cover A.png", 3),
                        ("Cover B.png", 3), ("Office spread.pdf", 7)]:
            put(root, f"{c}/Page drafts/{name}", d)
        for name, d in [("Proof 2 request.docx", 2), ("Proof review call 2026-10-14 notes.docx", 3),
                        ("Proof 1 comments.docx", 4), ("Proof 1.pdf", 5)]:
            put(root, f"{c}/Proofs/{name}", d)
        put(root, f"{c}/Proofs/Proof 1 (1).pdf", 5, 30)

        lo = f"{M}/Launches/Lounge seating launch"
        for name, d in [("Lounge launch plan.xlsx", 3), ("Lounge dealer briefing.docx", 4),
                        ("Lounge press release.docx", 5), ("Launch timeline.xlsx", 7), ("Lounge sample order.pdf", 11),
                        ("Lounge launch brief.docx", 16), ("Lounge naming options.docx", 22)]:
            put(root, f"{lo}/{name}", d)
        put(root, f"{lo}/Lounge press release (1).docx", 5)
        for name, d in [("Lounge sofa grey.jpg", 6), ("Lounge sofa oat.jpg", 6), ("Lounge chair.jpg", 9),
                        ("Lounge set.jpg", 9)]:
            put(root, f"{lo}/Photos/{name}", d)
        for i, d in enumerate(spread(170, 230, 7)):
            put(root, f"{M}/Launches/Desk range launch 2025/Desk range material {i + 1}.docx", d)

        w = f"{M}/Website refresh"
        for name, d in [("Website timeline.xlsx", 6), ("Page copy home.docx", 7), ("Website site map.xlsx", 8),
                        ("Page copy chairs.docx", 9), ("Navigation labels.xlsx", 9), ("Page copy desks.docx", 10),
                        ("Page copy lounge.docx", 11), ("Page copy contact.docx", 12),
                        ("Website search terms.xlsx", 13), ("Launch checklist.docx", 14),
                        ("Website photo brief.docx", 15), ("Website agency proposal.pdf", 25),
                        ("Website brief.docx", 30)]:
            put(root, f"{w}/{name}", d)
        for name, d in [("Competitor sites.xlsx", 18), ("User interviews.docx", 20), ("Analytics export.csv", 21),
                        ("Survey results.xlsx", 24)]:
            put(root, f"{w}/Research/{name}", d)
        for name, d in [("Site map v1.xlsx", 8), ("Site map v2.xlsx", 6)]:
            put(root, f"{w}/Oude versies/{name}", d)

        t = f"{M}/Case studies/Thistlemere College"
        for name, d in [("Thistlemere case study draft.docx", 9), ("Thistlemere quote approvals.docx", 10),
                        ("Thistlemere interview notes.docx", 12), ("Thistlemere call notes.docx", 14)]:
            put(root, f"{t}/{name}", d)
        for name, d in [("Thistlemere library.jpg", 17), ("Thistlemere atrium.jpg", 17)]:
            put(root, f"{t}/Photos/{name}", d)
        for i, d in enumerate(spread(110, 140, 5)):
            put(root, f"{M}/Case studies/Pellbrook Clinic/Pellbrook case study part {i + 1}.docx", d)

        for name, d in [("Awards entry text.docx", 14), ("Awards entry form.pdf", 16), ("Awards images.zip", 18),
                        ("Awards judging criteria.pdf", 30)]:
            put(root, f"{M}/Design awards entry/{name}", d)

        for i, d in enumerate(spread(35, 50, 8)):
            put(root, f"{M}/Competitor price check/Competitor prices {i + 1}.xlsx", d)
        for name, d in [("Brand guidelines draft.docx", 49), ("Brand colour list.xlsx", 52),
                        ("Brand type samples.pdf", 55), ("Brand logo usage.pdf", 57), ("Brand feedback.docx", 60)]:
            put(root, f"{M}/Brand guidelines update/{name}", d)
        for i, d in enumerate(spread(175, 200, 10)):
            put(root, f"2025/Dealer conference 2025/Dealer conference file {i + 1}.pptx", d)
        for i, d in enumerate(spread(295, 320, 8)):
            put(root, f"2025/Catalogue 2026/Catalogue 2026 part {i + 1}.pdf", d)
        put(root, f"{M}/Marketing plan 2027.docx", 13)

        for k in range(13):
            friday = datetime.datetime(2026, 10, 16) - datetime.timedelta(days=7 * k)
            put(root, f"{M}/Reporting/Weekly marketing report {friday:%Y-%m-%d}.docx", 1 + 7 * k)
        put(root, f"{M}/Reporting/Report distribution list.xlsx", 60)

        for i, d in enumerate(spread(0, 30, 25)):
            put(root, f"Chat Files/{rnd.choice(['image', 'Book', 'Presentation', 'export', 'file'])} ({i})."
                      f"{rnd.choice(['png', 'xlsx', 'pptx', 'pdf'])}", d)
        for i, d in enumerate(spread(0, 10, 10)):
            put(root, f"Desktop/Screenshot 2026-10-{17 - d:02d} at 1{i % 10}.0{i % 6}.41.png", d)
        for name, d in [("Catalogue cover sketch.png", 1), ("Untitled.docx", 0), ("Copy of Price pages draft.xlsx", 4),
                        ("Document11.docx", 3)]:
            put(root, f"Desktop/{name}", d)
        for name, d in [("Proof review call-20261014_100000-Meeting Recording.mp4", 3),
                        ("Lounge launch sync-20261013_150000-Meeting Recording.mp4", 4),
                        ("Website weekly-20261009_110000-Meeting Recording.mp4", 8),
                        ("Marketing all hands-20260925_090000-Meeting Recording.mp4", 22)]:
            put(root, f"Recordings/{name}", d)
        for name, d in [("Payslip September.pdf", 12), ("Payslip August.pdf", 40), ("Gym membership.pdf", 25),
                        ("Holiday photos.zip", 30)]:
            put(root, f"Personal/{name}", d)
        for name, d in [("Proposal template.docx", 3), ("Slide master.potx", 120), ("Letterhead.dotx", 300),
                        ("Press release template.docx", 90)]:
            put(root, f"Templates/{name}", d)
        for i, d in enumerate(spread(300, 900, 20)):
            put(root, f"Archive/Old campaigns/Campaign file {i + 1}.docx", d)
        put(root, "Archive/Moved from laptop/Price pages 2026.xlsx", 2)
        for i, d in enumerate(spread(300, 600, 10)):
            put(root, f"Archivio/Cataloghi/Catalogo {2018 + i % 6} parte {i + 1}.pdf", d)
        put(root, "Archivio/Listino prezzi rivenditori.xlsx", 2)
        for name, d in [("Listino 2026 vecchio.pdf", 4), ("Catalogo 2026 bozza.pdf", 6), ("Brochure sedute.pdf", 30)]:
            put(root, f"{M}/Vecchio - non usare/{name}", d)
        for name, d in [("Modello offerta.docx", 5), ("Modello comunicato stampa.docx", 80), ("Carta intestata.dotx", 200)]:
            put(root, f"Modelli/{name}", d)
        for name, d in [("Busta paga settembre.pdf", 12), ("Contratto affitto.pdf", 6), ("Visita medica.pdf", 20)]:
            put(root, f"Privato/{name}", d)
        for i, d in enumerate(spread(200, 400, 12)):
            put(root, f"Archief 2025/Beurs materiaal {i + 1}.pdf", d)
        for name, d in [("Dealerlijst Benelux.xlsx", 3), ("Prijslijst Benelux.xlsx", 3)]:
            put(root, f"Archief 2025/{name}", d)
        for name, d in [("Offerte sjabloon.docx", 8), ("Presentatie sjabloon.pptx", 150)]:
            put(root, f"Sjablonen/{name}", d)
        for name, d in [("Loonstrook september.pdf", 11), ("Reisverzekering.pdf", 9)]:
            put(root, f"Privé/{name}", d)
        for name, d in [("Beursstand 2024.pdf", 2), ("Dealerbrief 2024.docx", 5), ("Folder kantoorstoelen.pdf", 400)]:
            put(root, f"Oud/{name}", d)
        for name, d in [("Notes.docx", 2), ("Holiday rota.xlsx", 5), ("Untitled.docx", 7), ("Org chart.pdf", 39)]:
            put(root, name, d)
        for dirpath, dirnames, _ in list(os.walk(root)):
            put(root, os.path.relpath(os.path.join(dirpath, ".DS_Store"), root), 0, 1)
        put(root, "desktop.ini", 0, 1)

    def reports(self, root):
        """A folder the trial did not have: a piece of work holding its own weekly status report beside its
        plan, risk log and test results; two routines; and five old folders that score alike."""
        put = self.put
        s = "Clients/Tamsworth Mills/Stock system move"
        for k in range(12):
            put(root, f"{s}/Stock system move status 2026-W{41 - k:02d}.docx", 1 + 7 * k)
        for name, d in [("Cutover plan.xlsx", 2), ("Risk log.xlsx", 3), ("Test results.xlsx", 5),
                        ("Steering deck.pptx", 6), ("Data mapping.xlsx", 9)]:
            put(root, f"{s}/{name}", d)
        for m in range(4, 11):
            put(root, f"Reporting/Monthly sales report 2026-{m:02d}.xlsx", (10 - m) * 30 + 3)
        put(root, "Reporting/Distribution list.xlsx", 40)
        for k in range(10):
            day = datetime.date(2026, 10, 16) - datetime.timedelta(days=7 * k)
            put(root, f"Finance/Weekly cash report/Weekly cash report {day:%Y-%m-%d}.xlsx", 1 + 7 * k)
        for name, d in [("Cash forecast model.xlsx", 4), ("Bank contacts.xlsx", 30)]:
            put(root, f"Finance/Weekly cash report/{name}", d)
        for name, d in [("Floor plan.pdf", 4), ("Removals quote.pdf", 6), ("Seating plan.xlsx", 8)]:
            put(root, f"Internal/Office move/{name}", d)
        for name, d in [("Role profile.docx", 12), ("Candidates.xlsx", 15), ("Interview questions.docx", 20)]:
            put(root, f"Internal/Hiring round/{name}", d)
        # Old work that scores alike at three decimals, made in an order unlike its last activity.
        for name, d in [("Alder review", 400), ("Birch review", 300), ("Cedar review", 500), ("Damson review", 350),
                        ("Elder review", 450)]:
            for i in range(3):
                put(root, f"2023/{name}/{name} part {i + 1}.docx", d + 5 * i)


def build_fixtures(out: Path) -> dict:
    """The trial's three folders, made with its random draws in its order, then the reports folder and the
    worked example's drive. {name: folder}."""
    m = Maker(17)
    folders = {"corporate": out / "corporate" / "OneDrive - Fernhill Advisory", "flat": out / "flat" / "Documents",
               "quillfield": out / "drive" / "Quillfield Drive", "reports": out / "reports" / "Shared Work",
               "example": out / "example" / "Quillfield Shared"}
    for p in folders.values():
        p.mkdir(parents=True)
    m.corporate(str(folders["corporate"]))
    m.flat(str(folders["flat"]))
    m.quillfield(str(folders["quillfield"]))
    Maker(41).reports(str(folders["reports"]))
    spec = importlib.util.spec_from_file_location("garrick_example_build_discover", str(BUILD))
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    d = build.dates(EXAMPLE_DAY)
    build.lay_drive(folders["example"], build.fields(d), d)
    return folders


def manifest(root: Path) -> list:
    """Every folder and file under `root`, hidden ones too: sha256, size and modification time of each file."""
    rows = []
    for dp, dns, fns in os.walk(str(root)):
        for d in dns:
            p = os.path.join(dp, d)
            rows.append(("dir", os.path.relpath(p, str(root)), os.lstat(p).st_mtime_ns))
        for f in fns:
            p = os.path.join(dp, f)
            st = os.lstat(p)
            with open(p, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()
            rows.append(("file", os.path.relpath(p, str(root)), h, st.st_size, st.st_mtime_ns))
    st = os.lstat(str(root))
    rows.append(("root", st.st_mtime_ns))
    return sorted(rows, key=repr)


def workspace(base: Path) -> Path:
    root = base / "ws"
    (root / "System").mkdir(parents=True)
    (root / "System" / "rules.md").write_text("# Rules\n", encoding="utf-8")
    return root


TRUTH = {
    "corporate": ["Clients › Brightwater Energy › Grid audit 2026", "Clients › Halvorsen Logistics › Warehouse rollout",
                  "Internal › Team offsite 2026", "Clients › Ostrava Foods › Market entry study",
                  "Internal › Hiring - analyst role"],
    "flat": ["names with “Kestrel”", "names with “Marlow”", "names with “Pitch”", "names with “Q3”"],
    "quillfield": ["Marketing › Catalogue 2027", "Marketing › Launches › Lounge seating launch",
                   "Marketing › Website refresh", "Marketing › Case studies › Thistlemere College",
                   "Marketing › Design awards entry"],
    "example": ["Marketing › Kestle chair launch", "Customer service › Brannock delivery problem",
                "Sales › Ellisford University tender", "Finance › Dealer price list", "Marketing › Spring trade show"],
}
# What a user would recognise in each, from the trial's truth.json.
RECOGNISABLE = {
    "corporate": ["Grid audit 2026", "Warehouse rollout", "Team offsite 2026", "Market entry study",
                  "Hiring - analyst role", "Budget 2026 planning"],
    "flat": ["Kestrel", "Marlow", "Pitch", "Q3", "Office move"],
    "quillfield": ["Catalogue 2027", "Lounge seating launch", "Website refresh", "Thistlemere College",
                   "Design awards entry"],
}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name).resolve()
        cls.folders = build_fixtures(cls.base / "fx")
        cls.before = {k: manifest(v) for k, v in cls.folders.items()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def unchanged(self, label=""):
        for k, v in self.folders.items():
            self.assertEqual(self.before[k], manifest(v), "%s changed %s" % (k, label))

    def find(self, name: str, today=SCORED):
        """Discovery on one fixture, in this process, under the guard: any open under the folder fails."""
        folder = str(self.folders[name])
        with dc.guard(folder):
            return dc.discover(folder, today)

    def picked(self, name: str, today=SCORED):
        props, info = self.find(name, today)
        top, more = dc.pick(props)
        return top, more, info


class RulesTest(Base):
    """The rules of the trial, on the trial's folders."""

    def test_the_top_five_are_the_ones_a_user_would_recognise(self):
        for name, want in TRUTH.items():
            today = datetime.datetime(2026, 10, 20, 23, 59) if name == "example" else SCORED
            top, _, _ = self.picked(name, today)
            self.assertEqual(want, [p["label"] for p in top], name)
            for p in top:
                self.assertTrue(any(r in p["label"] for r in RECOGNISABLE.get(name, [p["label"]])), p["label"])
        self.unchanged()

    def test_nothing_older_than_sixty_days_in_the_top_and_two_files_at_least(self):
        for name in self.folders:
            top, more, _ = self.picked(name)
            if len(top) >= 3:
                self.assertTrue(all(p["days"] <= 60 for p in top), name)
            self.assertTrue(all(p["files"] >= 2 for p in top + more), name)
            self.assertLessEqual(len(top), 5)

    def test_a_flat_folder_is_said_to_be_flat_and_offered_as_name_groups(self):
        top, more, info = self.picked("flat")
        self.assertTrue(info["flat"])
        self.assertEqual({"names"}, {p["kind"] for p in top})
        kestrel = top[0]
        self.assertEqual(3, len(kestrel["latest"]))
        self.assertEqual("Kestrel data migration plan v3.docx", kestrel["latest"][0])
        self.assertEqual(kestrel["files"], len(kestrel["members"]))
        self.assertTrue(all("Kestrel" in m or "Onboarding" in m for m in kestrel["members"]), kestrel["members"])
        self.assertIn("weekly report", [r["name"] for r in info["routines"]])
        for name in ("corporate", "quillfield", "example", "reports"):
            props, info = self.find(name)
            self.assertFalse(info["flat"], name)
            self.assertNotIn("names", {p["kind"] for p in props}, name)

    def test_folders_left_out_by_name_in_three_languages_without_case_or_accents(self):
        cases = {
            "chat": ["Chat Files", "Teams Chat Files", "Microsoft Teams Chat Files", "Microsoft Teams-chatbestanden",
                     "File della chat di Microsoft Teams", "CHAT FILES"],
            "desktop": ["Desktop", "DESKTOP"],
            "personal": ["Personal", "Private", "Privato", "Privé", "PRIVÉ", "prive"],
            "templates": ["Templates", "Template", "Modelli", "Sjablonen", "Report templates"],
            "recordings": ["Recordings"],
            "archive": ["Archive", "Archived", "Archivio", "Archief 2025", "Project archive"],
            "old": ["Old", "Old - do not use", "Do not use", "Vecchio - non usare", "Listini vecchi", "Oude versies",
                    "Oud", "Niet gebruiken", "Prices old"],
            "assets": ["Brand assets", "Resources", "Image library"],
            "copy": ["Copy of Rollout"],
            "odds": ["Misc", "Stuff", "Unsorted", "New folder", "Downloads", "Shared with me", "_scratch", "zzz Spare",
                     "Backups", "Attachments"],
        }
        for why, names in cases.items():
            for n in names:
                self.assertEqual(why, dc.skip_reason(n), n)
                self.assertEqual("skip", dc.classify(n), n)
        for n in ("Catalogue 2027", "Website refresh", "Oldham office fit-out", "Archer account", "Golden Hour campaign",
                  "Template review"):
            self.assertIsNone(dc.skip_reason(n), n)
        _, _, info = self.picked("quillfield")
        left = {f: why for f, why in info["left"]}
        self.assertEqual({
            "Archief 2025": "archive", "Archive": "archive", "Archivio": "archive", "Chat Files": "chat",
            "Desktop": "desktop", "Marketing/Vecchio - non usare": "old",
            "Marketing/Website refresh/Oude versies": "old", "Modelli": "templates", "Oud": "old",
            "Personal": "personal", "Privato": "personal", "Privé": "personal", "Recordings": "recordings",
            "Sjablonen": "templates", "Templates": "templates"}, left)

    def test_stage_part_and_media_folders_count_toward_their_parent(self):
        for n in ("Draft", "Drafts", "Final", "Working", "Proofs", "Proof 2", "Page drafts", "Printer proofs",
                  "Draft v3", "v2", "Redlines", "Signed"):
            self.assertTrue(dc.is_stage(dc.norm(n)), n)
            self.assertEqual("part", dc.classify(n), n)
        for n in ("Research", "Notes", "Photos", "Photo selects", "Images", "Correspondence"):
            self.assertEqual("part", dc.classify(n), n)
        for n in ("Review of suppliers", "Copy", "Draft budget"):
            self.assertEqual("unit", dc.classify(n), n)
        props, _ = self.find("quillfield")
        by = {p["label"]: p for p in props}
        self.assertEqual(21, by["Marketing › Catalogue 2027"]["files"])
        self.assertFalse([l for l in by if "Page drafts" in l or "Proofs" in l or "Photos" in l or "Research" in l])
        props, _ = self.find("corporate")
        by = {p["label"]: p for p in props}
        self.assertEqual(7, by["Clients › Halvorsen Logistics › Warehouse rollout"]["files"])   # Working, Draft, Final
        self.assertEqual(9, by["Clients › Brightwater Energy › Grid audit 2026"]["files"])

    def test_year_folders_and_grouping_folders_are_walked_through_never_proposed(self):
        props, _ = self.find("corporate")
        labels = [p["label"] for p in props]
        for never in ("Clients", "Internal", "2024", "2025"):
            self.assertNotIn(never, labels)
        self.assertIn("2025 › Budget 2026 planning", labels)
        self.assertIn("2024 › Q1 Board pack", labels)
        for n in ("2025", "Clients", "Customers", "Internal"):
            self.assertEqual("container", dc.classify(n), n)

    def test_a_routine_is_listed_and_never_proposed(self):
        props, info = self.find("quillfield")
        self.assertEqual([("Marketing/Reporting", "weekly marketing report", 14)],
                         [(r["folder"], r["name"], r["files"]) for r in info["routines"]])
        self.assertNotIn("Marketing › Reporting", [p["label"] for p in props])

    def test_a_piece_of_work_with_its_own_weekly_status_report_is_still_proposed(self):
        """The design note's build point: two thirds and four dates alone would drop this folder."""
        props, info = self.find("reports")
        by = {p["label"]: p for p in props}
        stock = by["Clients › Tamsworth Mills › Stock system move"]
        self.assertEqual(17, stock["files"])
        self.assertEqual({"name": "stock system move status", "files": 12}, stock["series"])
        top, _ = dc.pick(props)
        self.assertEqual("Clients › Tamsworth Mills › Stock system move", top[0]["label"])
        # The first two conditions hold, so the trial's rule would have called it a routine.
        files = dc.work_files(self.folders["reports"] / "Clients" / "Tamsworth Mills" / "Stock system move")
        self.assertEqual(("stock system move status", 12), dc.series(files))
        self.assertGreaterEqual(12, dc.ROUTINE_SHARE * len(files))
        self.assertIsNone(dc.is_routine(files))
        # A report folder with one or two other files is still a routine.
        routines = {r["folder"]: r for r in info["routines"]}
        self.assertEqual({"Reporting", "Finance/Weekly cash report"}, set(routines))
        self.assertEqual(12, routines["Finance/Weekly cash report"]["files"])
        self.assertEqual("monthly sales report", routines["Reporting"]["name"])

    def test_drafts_of_one_thing_are_not_a_routine(self):
        class Fake:
            def __init__(self, name):
                self.name = name
        drafts = [Fake(n) for n in ("Proposal v1.docx", "Proposal v2.docx", "Proposal v3 FINAL.docx",
                                    "Proposal v4.docx", "Proposal final.docx")]
        self.assertIsNone(dc.is_routine(drafts))

    def test_a_copy_counts_once_and_junk_is_ignored(self):
        _, _, info = self.picked("quillfield")
        self.assertEqual(2, info["copies"])
        props, _ = self.find("quillfield")
        every = [n for p in props for n in p["latest"]]
        self.assertFalse([n for n in every if n.startswith(("~$", ".")) or n == "desktop.ini" or "(1)" in n], every)
        lounge = next(p for p in props if p["name"] == "Lounge seating launch")
        self.assertEqual(11, lounge["files"])          # 7, the photos, and the press release once
        _, _, info = self.picked("flat")
        self.assertEqual(2, info["copies"])
        for n in (".DS_Store", "~$nal report.docx", "desktop.ini", "Thumbs.db", "Icon\r", "x.tmp"):
            self.assertTrue(dc.is_junk(n), n)

    def test_loose_files_at_the_top_of_a_tree_are_listed_never_proposed(self):
        props, info = self.find("quillfield")
        self.assertEqual(["Notes.docx", "Holiday rota.xlsx", "Untitled.docx", "Org chart.pdf"], info["loose"])
        self.assertFalse([p for p in props if p["folder"] == "."])
        props, info = self.find("corporate")
        self.assertEqual(["Expenses October.xlsx", "Document1.docx", "Proposal.docx", "Final report.docx"], info["loose"])

    def test_ties_under_more_are_ordered_by_last_activity(self):
        top, more, _ = self.picked("reports")
        old = [p for p in more if p["label"].startswith("2023 › ")]
        self.assertEqual(["Birch review", "Damson review", "Alder review", "Elder review", "Cedar review"],
                         [p["name"] for p in old])
        self.assertEqual({0.0}, {p["score"] for p in old})
        for name in self.folders:
            _, more, _ = self.picked(name)
            for a, b in zip(more, more[1:]):
                if a["score"] == b["score"]:
                    self.assertGreaterEqual(a["last"], b["last"], (name, a["label"], b["label"]))
        _, more, _ = self.picked("corporate")
        labels = [p["label"] for p in more]
        self.assertLess(labels.index("Clients › Pellham Bank › Onboarding"), labels.index("2024 › Q2 Board pack"))

    def test_ids_stay_the_same_scan_after_scan(self):
        a, _ = self.find("quillfield")
        b, _ = self.find("quillfield")
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertEqual(len(a), len({p["id"] for p in a}))


class GuardTest(unittest.TestCase):
    """Discovery refuses to open or write anything under the picked folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name).resolve() / "Picked"
        (self.folder / "Work").mkdir(parents=True)
        self.file = self.folder / "Work" / "Plan.docx"
        self.file.write_bytes(b"plan")
        self.outside = Path(self.tmp.name).resolve() / "outside.txt"
        self.outside.write_text("free", encoding="utf-8")
        self.before = manifest(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_open_and_every_write_under_the_folder_is_refused(self):
        attempts = {
            "read": lambda: open(str(self.file), "rb").close(),
            "os.open": lambda: os.close(os.open(str(self.file), os.O_RDONLY)),
            "write": lambda: open(str(self.folder / "new.txt"), "w").close(),
            "mkdir": lambda: os.mkdir(str(self.folder / "New")),
            "utime": lambda: os.utime(str(self.file), (0, 0)),
            "rename": lambda: os.rename(str(self.file), str(self.folder / "Moved.docx")),
            "move in": lambda: os.rename(str(self.outside), str(self.folder / "in.txt")),
            "remove": lambda: os.remove(str(self.file)),
            "rmdir": lambda: os.rmdir(str(self.folder / "Work")),
            "chmod": lambda: os.chmod(str(self.file), 0o600),
            "copy in": lambda: shutil.copyfile(str(self.outside), str(self.folder / "copy.txt")),
            "rmtree": lambda: shutil.rmtree(str(self.folder / "Work")),
            "through a link": lambda: open(str(Path(self.tmp.name) / "link" / "Work" / "Plan.docx"), "rb").close(),
        }
        os.symlink(str(self.folder), str(Path(self.tmp.name) / "link"))
        with dc.guard(self.folder):
            for what, attempt in attempts.items():
                with self.assertRaises(PermissionError, msg=what):
                    attempt()
            self.assertEqual("free", self.outside.read_text(encoding="utf-8"))     # outside is untouched by the guard
            names = sorted(e.name for e in os.scandir(str(self.folder)))          # listing is allowed
            self.assertEqual(["Work"], names)
        self.assertEqual(self.before, manifest(self.folder))
        with open(str(self.file), "rb") as fh:                                     # disarmed once out
            self.assertEqual(b"plan", fh.read())

    def test_a_guard_that_lets_reads_through_still_refuses_writes(self):
        exempt = self.folder / "Garrick" / "System" / "generated"
        exempt.mkdir(parents=True)
        with dc.guard(self.folder, exempt=(exempt,), reads=False):
            with open(str(self.file), "rb") as fh:
                self.assertEqual(b"plan", fh.read())
            for mode in ("wb", "ab", "r+b", "xb"):
                with self.assertRaises(PermissionError, msg=mode):
                    open(str(self.file) if mode != "xb" else str(self.folder / "x"), mode).close()
            (exempt / "state.json").write_text("{}", encoding="utf-8")            # the exempt folder may be written
        (exempt / "state.json").unlink()
        for p in (exempt, exempt.parent, exempt.parent.parent):
            p.rmdir()
        # The test made and removed the exempt folder itself, so the picked folder's own date moved; nothing else.
        self.assertEqual(self.before[:-1], manifest(self.folder)[:-1])

    def test_the_command_runs_under_the_guard(self):
        """A scan in a fresh process, with discovery made to open a file: refused, and nothing is recorded."""
        root = workspace(Path(self.tmp.name))
        code = ("import runpy, sys, os\n"
                "sys.argv = ['discover.py', '--root', %r, 'scan', %r]\n"
                "sys.path.insert(0, %r)\n"
                "import discover\n"
                "def peek(folder):\n"
                "    open(os.path.join(%r, 'Work', 'Plan.docx'), 'rb').read()\n"
                "discover.discover = lambda *a, **k: peek(None)\n"
                "sys.exit(discover.main(sys.argv[1:]))\n") % (str(root), str(self.folder), str(TOOLS), str(self.folder))
        res = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=ENV)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("discovery must not open", res.stderr)
        self.assertFalse((root / "System" / "generated" / "discovery.json").exists())
        self.assertEqual(self.before, manifest(self.folder))


class CommandTest(Base):
    """scan, answer and list, each in a fresh process, as the page and the assistant run them."""

    def setUp(self):
        self.ws_tmp = tempfile.TemporaryDirectory()
        self.root = workspace(Path(self.ws_tmp.name).resolve())
        self.said = []

    def tearDown(self):
        self.ws_tmp.cleanup()

    def tool(self, *args, ok=True, json_out=True, env=None):
        cmd = [sys.executable, "-B", str(TOOL), "--root", str(self.root), "--today", AS_OF]
        if json_out:
            cmd.append("--json")
        res = subprocess.run(cmd + [str(a) for a in args], capture_output=True, text=True, env=env or ENV)
        self.unchanged(" by %s" % " ".join(map(str, args)))
        if ok:
            self.assertEqual(0, res.returncode, res.stderr + res.stdout)
        else:
            self.assertEqual(1, res.returncode, res.stderr + res.stdout)
        if not json_out:
            self.said.append(res.stdout + res.stderr)
            return res.stdout + res.stderr
        out = json.loads(res.stdout)
        if "said" in out:
            self.said.append(out["said"])
        if "error" in out:
            self.said.append(out["error"])
        return out

    def state(self):
        return json.loads((self.root / "System" / "generated" / "discovery.json").read_text(encoding="utf-8"))

    def test_answers_survive_a_restart_and_a_rescan(self):
        folder = self.folders["quillfield"]
        first = self.tool("scan", folder)
        top = first["top"]
        self.assertEqual(TRUTH["quillfield"], [p["label"] for p in top])
        catalogue, lounge, website = top[0], top[1], top[2]
        yes = self.tool("answer", catalogue["id"], "yes")
        self.assertEqual(("yes", "Catalogue 2027"), (yes["answer"], yes["name"]))
        renamed = self.tool("answer", lounge["id"], "rename", "Lounge", "launch")
        self.assertEqual(("yes", "Lounge launch"), (renamed["answer"], renamed["name"]))
        not_ = self.tool("answer", website["id"], "not")
        self.assertEqual("not", not_["answer"])
        again = self.tool("scan", folder)                           # a new process: a restart
        labels = [p["label"] for p in again["top"]]
        self.assertNotIn(catalogue["label"], labels)
        self.assertNotIn(website["label"], labels + [p["label"] for p in again["more"]])
        self.assertEqual(["Marketing › Case studies › Thistlemere College", "Marketing › Design awards entry"],
                         labels[:2])                                 # unanswered ones stay, first
        self.assertEqual({"Catalogue 2027", "Lounge launch"}, {p["name"] for p in again["confirmed"]})
        self.assertIn({"folder": "Marketing/Website refresh", "why": "declined",
                       "said": "not a piece of work, as you said"}, again["left_out"])
        self.assertIn("not a piece of work, as you said (Marketing › Website refresh)", again["left_out_said"])
        answers = self.state()["folders"][str(folder)]["answers"]
        self.assertEqual({catalogue["id"]: "yes", lounge["id"]: "yes", website["id"]: "not"},
                         {k: v["answer"] for k, v in answers.items()})
        self.assertEqual(str(folder / "Marketing" / "Catalogue 2027"), answers[catalogue["id"]]["path"])
        listed = self.tool("list")
        self.assertEqual([str(folder)], [f["folder"] for f in listed["folders"]])
        text = self.tool("list", json_out=False)
        self.assertIn("Yours: ", text)
        self.assertIn("Lounge launch", text)
        self.assertIn("Not a piece of work: Marketing › Website refresh.", text)
        # A changed mind is recorded too, and the folder comes back.
        self.tool("answer", website["id"], "yes")
        back = self.tool("scan", folder)
        self.assertIn("Website refresh", {p["name"] for p in back["confirmed"]})
        self.assertFalse([l for l in back["left_out"] if l["why"] == "declined"])

    def test_a_name_group_in_a_flat_folder_is_answered_the_same_way(self):
        folder = self.folders["flat"]
        out = self.tool("scan", folder)
        self.assertTrue(out["flat"])
        kestrel = out["top"][0]
        self.assertEqual("names", kestrel["kind"])
        rec = self.tool("answer", kestrel["id"], "rename", "Kestrel onboarding")
        self.assertEqual(sorted(kestrel["members"]), rec["members"])
        again = self.tool("scan", folder)
        self.assertEqual(["Kestrel onboarding"], [p["name"] for p in again["confirmed"]])
        self.assertNotIn(kestrel["id"], [p["id"] for p in again["top"] + again["more"]])

    def test_refusals_say_why_and_change_nothing(self):
        out = self.tool("answer", "deadbeef", "yes", ok=False)
        self.assertIn("No proposal has the id deadbeef", out["error"])
        first = self.tool("scan", self.folders["example"])
        pid = first["top"][0]["id"]
        bad = self.tool("answer", pid, "rename", "Kestle/launch", ok=False)
        self.assertIn("cannot be the name of a piece of work", bad["error"])
        self.tool("answer", pid, "rename", ok=False)
        self.tool("scan", self.base / "no such folder", ok=False)
        refused = self.tool("scan", self.root / "System", ok=False)
        self.assertIn("part of Garrick itself", refused["error"])
        home = self.tool("scan", self.folders["example"], ok=False, env=dict(ENV, HOME=str(self.folders["example"])))
        self.assertIn("whole home folder", home["error"])
        self.tool("scan", "/", ok=False)
        self.assertEqual({}, self.state()["folders"][str(self.folders["example"])]["answers"])

    def test_the_state_lives_in_the_workspace_and_is_machine_state(self):
        for name, folder in self.folders.items():
            self.tool("scan", folder)
        state = self.state()
        self.assertEqual(sorted(str(f) for f in self.folders.values()), sorted(state["folders"]))
        for real, entry in state["folders"].items():
            self.assertEqual(dc.folder_key(real), entry["key"])
            for p in entry["top"] + entry["more"]:
                self.assertFalse([k for k in p if k.startswith("_")])
        self.assertEqual(["discovery.json"], sorted(p.name for p in (self.root / "System" / "generated").iterdir()))

    def test_a_folder_that_holds_the_workspace_leaves_it_out(self):
        tmp = Path(self.ws_tmp.name).resolve() / "Home docs"
        for rel, days in (("Tender/Response.docx", 2), ("Tender/Pricing.xlsx", 3), ("Garden/Plan.docx", 5),
                          ("Garden/Plants.xlsx", 6)):
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
            t = (TODAY - datetime.timedelta(days=days)).timestamp()
            os.utime(str(p), (t, t))
        inner = workspace(tmp)

        def outside(rows):
            return [r for r in rows if not (isinstance(r[1], str) and (r[1] == "ws" or r[1].startswith("ws" + os.sep)))]
        before = outside(manifest(tmp))
        res = subprocess.run([sys.executable, "-B", str(TOOL), "--root", str(inner), "--today", AS_OF, "--json",
                              "scan", str(tmp)], capture_output=True, text=True, env=ENV)
        self.assertEqual(0, res.returncode, res.stderr)
        out = json.loads(res.stdout)
        self.assertEqual({"Tender", "Garden"}, {p["name"] for p in out["top"]})
        self.assertIn({"folder": "ws", "why": "garrick", "said": "Garrick's own folder"}, out["left_out"])
        self.assertTrue((inner / "System" / "generated" / "discovery.json").is_file())
        self.assertEqual(before, outside(manifest(tmp)))

    def test_plain_words_and_the_text_form(self):
        for name, folder in self.folders.items():
            text = self.tool("scan", folder, json_out=False)
            self.assertIn("most recently active first", text)
            self.assertIn("Latest: ", text)
        flat = self.tool("scan", self.folders["flat"], json_out=False)
        self.assertIn("Documents is a flat folder", flat)
        self.assertIn("these 8 files", flat)
        quill = self.tool("scan", self.folders["quillfield"], json_out=False)
        self.assertIn("Left out: archives (Archief 2025, Archive, Archivio); chat files (Chat Files); the desktop "
                      "(Desktop)", quill)
        self.assertIn("a report made again and again (Marketing › Reporting)", quill)
        self.assertIn("Loose files at the top, not proposed: Notes.docx; Holiday rota.xlsx; Untitled.docx; "
                      "Org chart.pdf.", quill)
        reports = self.tool("scan", self.folders["reports"], json_out=False)
        self.assertIn("It also holds a report made again and again: stock system move status, 12 files.", reports)
        pid = self.tool("scan", self.folders["quillfield"])["top"][0]["id"]
        self.tool("answer", pid, "not", json_out=False)
        self.tool("answer", pid, "yes", json_out=False)
        self.tool("list", json_out=False)
        self.tool("answer", "deadbeef", "yes", json_out=False, ok=False)
        self.tool("scan", self.root / "System", json_out=False, ok=False)
        for text in self.said:
            self.assertIsNone(UNSAID.search(text), text)


if __name__ == "__main__":
    unittest.main()
