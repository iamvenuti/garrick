"""Ask makes a project or a thread (#345), through the action the page's buttons run.

The session proposes `new-project` and `new-thread`; ask.py checks each against the workspace list and
System/context.md, asks where the request does not settle the party, runs scaffold.py's check-name, and then
page_action.perform() does the rest: the name check, the commit, the wall check, the record. No model is
called: FakeSession answers.

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

import test_scaffold_manage as manage  # noqa: E402
from fixtures import write  # noqa: E402
from test_ask import FakeSession, ask  # noqa: E402
from test_ask import AskCase as _AskCase  # noqa: E402
from test_page_action import git  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class MakeCase(_AskCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(REPO / "template" / "System" / "templates", self.root / "System" / "templates", dirs_exist_ok=True)
        self.names = ask.scan(self.root)

    def propose(self, a, named=None):
        return ask.proposal(a, self.names, self.root, named)

    def run_ask(self, request, *answers, asker=None):
        asker = asker or ask.Asker(self.root, FakeSession(*[json.dumps(a) for a in answers]))
        return asker, asker.ask(request)

    def head(self):
        return git(self.work, "log", "-1", "--format=%s").strip()

    def clean(self):
        return git(self.work, "status", "--porcelain").strip() == ""


class TestProposals(MakeCase):
    def test_a_thread_in_a_project_the_list_has(self):
        self.assertEqual(("act", {"verb": "new-thread", "zone": "Work", "project": "Acme Review", "name": "Renewal"}),
                         self.propose({"verb": "new-thread", "zone": "Work", "project": "Acme Review", "name": " Renewal "}))

    def test_a_thread_needs_a_zone_and_a_project_the_list_has(self):
        for a in ({"zone": "Work", "project": "Nope", "name": "Renewal"}, {"zone": "Work", "name": "Renewal"},
                  {"zone": "Elsewhere", "project": "Acme Review", "name": "Renewal"},
                  {"zone": "Personal", "project": "Acme Review", "name": "Renewal"},      # a project of another zone
                  {"project": "Acme Review", "name": "Renewal"}):
            with self.assertRaises(ask.Bad, msg=a):
                self.propose(dict(a, verb="new-thread"))

    def test_a_name_is_text_on_one_line(self):
        for name in (None, "", "   ", "-rf", "two\nlines", 7, "x" * 81):
            with self.assertRaises(ask.Bad, msg=name):
                self.propose({"verb": "new-thread", "zone": "Work", "project": "Acme Review", "name": name})
            with self.assertRaises(ask.Bad, msg=name):
                self.propose({"verb": "new-project", "zone": "Work", "name": name, "party": "birch"}, {"birch"})

    def test_a_project_for_the_party_the_request_named(self):
        got = self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch",
                            "thread": "Launch Plan"}, {"birch"})
        self.assertEqual(("act", {"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch",
                                  "thread": "Launch Plan"}), got)
        for party in ("Birch & Co", "BIRCH", "`birch`"):                    # a name or a tag, as System/context.md writes it
            self.assertEqual("birch", self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                    "party": party}, {"birch"})[1]["party"], party)
        self.assertEqual(ask.FIRST_THREAD, got and self.propose(
            {"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}, {"birch"})[1]["thread"])
        # a request that names exactly one party of the zone settles it when the session left the party out
        self.assertEqual("acme", self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour"}, {"acme"})[1]["party"])

    def test_no_party_named_is_asked_with_a_choice_for_each_candidate_and_nothing_else(self):
        with self.assertRaises(ask.Needs) as e:
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour"}, set())
        self.assertEqual("Which party is Harbour for: Acme Corp or Birch & Co?", e.exception.question)
        self.assertEqual([{"label": "Acme Corp", "request": "Acme Corp"}, {"label": "Birch & Co", "request": "Birch & Co"}],
                         e.exception.choices)

    def test_a_pick_the_request_never_made_is_asked_about_not_used(self):
        with self.assertRaises(ask.Needs) as e:     # the session chose birch; the request named nothing
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}, set())
        self.assertIn("Acme Corp or Birch & Co", e.exception.question)
        with self.assertRaises(ask.Needs):          # the session chose birch; the request named acme
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}, {"acme"})
        with self.assertRaises(ask.Needs) as e:     # two named: asked between those two
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}, {"acme", "birch"})
        self.assertEqual(["Acme Corp", "Birch & Co"], [c["label"] for c in e.exception.choices])
        with self.assertRaises(ask.Needs):          # no named set at all: fail closed
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"})

    def test_a_party_that_is_not_in_context_is_refused_with_one_line(self):
        with self.assertRaisesRegex(ask.Bad, r"^Cobalt Freight is not a party in System/context.md. Add it in a session "
                                             r"first: a party decides which side of a wall material lands on.$"):
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "Cobalt Freight"}, {"birch"})

    def test_a_party_of_another_zone_is_refused(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| Birch & Co | Client. Market-entry advice; competes with Acme | Work |",
                                               "| Birch & Co | Client. Market-entry advice; competes with Acme | Personal |"))
        with self.assertRaisesRegex(ask.Bad, "^Birch & Co is a party of Personal, not of Work$"):
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}, {"birch"})
        with self.assertRaises(ask.Needs) as e:     # and Work's own are the candidates, not Personal's
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour"}, set())
        self.assertEqual(["Acme Corp"], [c["label"] for c in e.exception.choices])

    def test_a_zone_with_no_party_is_refused(self):
        with self.assertRaisesRegex(ask.Bad, "^No party is set up in Personal yet. Add one in a session first"):
            self.propose({"verb": "new-project", "zone": "Personal", "name": "Harbour", "party": "birch"}, {"birch"})

    def test_two_rows_with_one_name_are_told_apart_by_tag(self):
        ctx = self.root / "System" / "context.md"
        ctx.write_text(ctx.read_text().replace("| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` |",
                                               "| Acme Corp | The other hat | Work | `acme-adv` |\n"
                                               "| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` |"))
        with self.assertRaises(ask.Needs) as e:
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour"}, {"acme", "acme-adv"})
        self.assertEqual(["Acme Corp (acme)", "Acme Corp (acme-adv)"], [c["label"] for c in e.exception.choices])

    def test_a_long_list_of_parties_is_not_made_into_buttons(self):
        ctx = self.root / "System" / "context.md"
        rows = "".join("| Party %d | x | Work | `p%d` |  |\n" % (i, i) for i in range(10))
        ctx.write_text(ctx.read_text().replace("\n## Walls", rows + "\n## Walls"))
        with self.assertRaises(ask.Needs) as e:
            self.propose({"verb": "new-project", "zone": "Work", "name": "Harbour"}, set())
        self.assertEqual([], e.exception.choices)
        self.assertEqual("Which party is Harbour for in Work? Say its name.", e.exception.question)


class TestMakingThem(MakeCase):
    def test_a_new_thread_is_made_committed_and_offers_undo(self):
        asker, out = self.run_ask("new thread Renewal in Acme Review",
                                  {"say": "Making it.", "do": [{"verb": "new-thread", "zone": "Work",
                                                                "project": "Acme Review", "name": "Renewal"}]})
        self.assertEqual((True, "command"), (out["ok"], out["kind"]))
        self.assertEqual(["Created thread Renewal in Acme Review."], out["done"])
        self.assertTrue((self.work / "Acme Review" / "Threads" / "Renewal" / "Renewal.md").is_file())
        self.assertEqual("Acme Review: new thread Renewal", self.head())
        self.assertTrue(self.clean())
        self.assertEqual("new-thread", out["acted"][0]["request"]["verb"])         # the page moves it at once
        self.assertTrue(out["acted"][0]["reply"]["ok"])
        self.assertTrue(asker.session.seen[0].endswith("<request>\nnew thread Renewal in Acme Review\n</request>"))
        self.assertTrue((self.jobs / "page-actions.log").read_text().splitlines()[-1].endswith("(ask)"))
        # Undo is the page's own: page_action.py's `undo`, offered as a button
        [undo] = out["choices"]
        self.assertEqual("Undo", undo["label"])
        self.assertEqual({"verb": "undo", "zone": "Work"}, {k: v for k, v in undo["act"].items() if k != "commit"})
        pa = ask.page_action()
        reply, _, why = pa.perform(self.root, undo["act"], pa.ops_lib(self.root))
        self.assertTrue(reply["ok"], why)
        self.assertFalse((self.work / "Acme Review" / "Threads" / "Renewal").exists())

    def test_a_new_project_is_made_with_its_first_thread(self):
        asker, out = self.run_ask("new project Harbour for Birch & Co in Work",
                                  {"say": "Making it.", "do": [{"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                                "party": "birch", "thread": "Launch Plan"}]})
        self.assertEqual((True, ["Created project Harbour in Work, with its first thread, Launch Plan."]),
                         (out["ok"], out["done"]))
        hub = (self.work / "Harbour" / "Harbour.md").read_text()
        self.assertIn("party: birch", hub)
        self.assertTrue((self.work / "Harbour" / "Threads" / "Launch Plan" / "Launch Plan.md").is_file())
        self.assertEqual("New project Harbour (birch), first thread Launch Plan", self.head())
        self.assertTrue(self.clean())
        self.assertEqual("Undo", out["choices"][0]["label"])
        self.assertIn("birch", asker.heard)                  # the session now holds that party, for the wall reset

    def test_no_first_thread_named_is_getting_started(self):
        _, out = self.run_ask("new project Harbour for Birch & Co in Work",
                              {"say": "Making it.", "do": [{"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                            "party": "birch"}]})
        self.assertTrue(out["ok"], out["done"])
        self.assertTrue((self.work / "Harbour" / "Threads" / "Getting started" / "Getting started.md").is_file())

    def test_no_party_named_asks_and_writes_nothing_until_it_is_answered(self):
        proposal = {"verb": "new-project", "zone": "Work", "name": "Harbour", "party": "birch"}
        asker, out = self.run_ask("new project Harbour in Work", {"say": "Making it.", "do": [proposal]})
        self.assertEqual("clarify", out["kind"])
        self.assertEqual("Which party is Harbour for: Acme Corp or Birch & Co?", out["say"])
        self.assertEqual(["Acme Corp", "Birch & Co"], [c["label"] for c in out["choices"]])
        self.assertEqual(([], False), (out["done"], (self.work / "Harbour").exists()))
        self.assertEqual("start", self.head())
        self.assertTrue(self.clean())
        self.assertIsNotNone(asker.unclear)                   # the request waits, as one about a name that fits two does
        # the answer, typed or by its button, is the choice's request: the party's name
        asker.session.answers.append(json.dumps({"say": "Making it.", "do": [proposal]}))
        out = asker.ask(out["choices"][1]["request"])
        self.assertEqual(("command", True), (out["kind"], out["ok"]))
        self.assertTrue((self.work / "Harbour" / "Harbour.md").is_file())
        self.assertIn("<earlier-request>\nnew project Harbour in Work\n</earlier-request>", asker.session.seen[1])

    def test_a_party_that_is_not_there_is_refused_and_nothing_is_written(self):
        _, out = self.run_ask("new project Harbour for Cobalt Freight in Work",
                              {"say": "Making it.", "do": [{"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                            "party": "Cobalt Freight"}]})
        self.assertFalse(out["ok"])
        self.assertTrue(out["done"][0].startswith("Refused: Cobalt Freight is not a party in System/context.md. Add it in a session"))
        self.assertEqual(("start", False), (self.head(), (self.work / "Harbour").exists()))
        self.assertTrue(self.clean())

    def test_a_name_that_will_not_do_is_refused_in_scaffolds_words_and_nothing_is_written(self):
        for name, said in (("Pricing", "already has a thread called pricing"), ("Q4_Plan", "will not work as a thread name"), ("Q4, Plan", "does not belong in a name")):
            _, out = self.run_ask("new thread %s in Acme Review" % name,
                                  {"say": "Making it.", "do": [{"verb": "new-thread", "zone": "Work",
                                                                "project": "Acme Review", "name": name}]})
            self.assertFalse(out["ok"], name)
            self.assertTrue(out["done"][0].startswith("Refused: "), out["done"])
            self.assertIn(said, out["done"][0].lower(), name)
            self.assertEqual([], out["choices"])
            self.assertEqual("start", self.head())
            self.assertTrue(self.clean())
        log = (self.jobs / "page-actions.log").read_text().splitlines()
        self.assertTrue(all("refused" in l and l.endswith("(ask)") for l in log[-3:]))

    def test_a_name_a_sibling_already_has_is_refused_with_scaffolds_question(self):
        scaffold = ask.page_action().scaffold
        with self.assertRaises(ask.page_action().Refused) as e:
            scaffold(self.root, "thread", "--zone", "Work", "--project", "Acme Review", "--name", "Pricing", "--check")
        _, out = self.run_ask("new thread Pricing in Acme Review",
                              {"say": "Making it.", "do": [{"verb": "new-thread", "zone": "Work",
                                                            "project": "Acme Review", "name": "Pricing"}]})
        self.assertEqual(["Refused: " + str(e.exception)], out["done"])

    def test_a_project_name_that_exists_is_refused(self):
        _, out = self.run_ask("new project Birch Entry for Birch & Co in Work",
                              {"say": "Making it.", "do": [{"verb": "new-project", "zone": "Work", "name": "Birch Entry",
                                                            "party": "birch"}]})
        self.assertFalse(out["ok"])
        self.assertTrue(out["done"][0].startswith("Refused: "))
        self.assertEqual("start", self.head())

    def test_a_wall_the_commit_check_holds_is_the_rules_sentence_and_nothing_is_left(self):
        import check
        line = check.report_staged([check.Finding(check.ERROR, "walls", "Harbour/Harbour.md",
                                                  "names Acme Corp (`acme`), or one of its people; "
                                                  "a wall stands between acme and birch")])
        hook = self.work / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\ncat >&2 <<'EOF'\n%s\nEOF\nexit 1\n" % line)
        hook.chmod(0o755)
        _, out = self.run_ask("new project Harbour for Birch & Co in Work",
                              {"say": "Making it.", "do": [{"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                            "party": "birch"}]})
        pa = ask.page_action()
        self.assertEqual((False, [pa.ops_lib(self.root).WALL_REFUSAL]), (out["ok"], out["done"]))
        self.assertFalse((self.work / "Harbour").exists())
        self.assertTrue(self.clean())
        self.assertNotIn("acme", (self.jobs / "page-actions.log").read_text())

    def test_a_party_across_a_wall_from_what_the_session_heard_starts_a_fresh_session(self):
        asker = ask.Asker(self.root, FakeSession(json.dumps({"say": "ok", "do": []}),
                                                 json.dumps({"say": "Making it.", "do": [
                                                     {"verb": "new-project", "zone": "Work", "name": "Harbour",
                                                      "party": "birch"}]})))
        asker.ask("what is open for Acme Corp")
        out = asker.ask("new project Harbour for Birch & Co in Work")
        self.assertEqual("wall", out.get("reset"))                   # before the request reached the session
        self.assertTrue(out["ok"], out["done"])

    def test_the_zone_is_never_guessed(self):
        _, out = self.run_ask("new thread Renewal in Acme Review",
                              {"say": "Making it.", "do": [{"verb": "new-thread", "project": "Acme Review", "name": "Renewal"}]})
        self.assertFalse(out["ok"])
        self.assertTrue(out["done"][0].startswith("Refused: "))
        self.assertFalse((self.work / "Acme Review" / "Threads" / "Renewal").exists())

    def test_with_codex_the_two_verbs_work_the_same_way(self):
        session = FakeSession(json.dumps({"say": "Making it.", "do": [{"verb": "new-thread", "zone": "Work",
                                                                       "project": "Acme Review", "name": "Renewal"}]}))
        session.remembers = False                                    # Codex runs the box's commands, not its answers
        out = ask.Asker(self.root, session).ask("new thread Renewal in Acme Review")
        self.assertTrue(out["ok"], out["done"])
        self.assertTrue((self.work / "Acme Review" / "Threads" / "Renewal").is_dir())
        self.assertIn("make a project or a thread", ask.NEED_CLAUDE)

    def test_only_the_ask_flag_is_needed(self):
        self.assertEqual(("open", "park", "wake", "todo-add", "new-project", "new-thread"), ask.VERBS)

    def test_the_brief_tells_the_session_about_both(self):
        brief = (REPO / "extras" / "status" / "ask-brief.md").read_text(encoding="utf-8")
        for needle in ('{"verb": "new-thread", "zone": Z, "project": P, "name": N}',
                       '{"verb": "new-project", "zone": Z, "name": N, "party": "<tag>"'):
            self.assertIn(needle, brief)
        self.assertIn("never make a party", " ".join(brief.split()))


class TestTheAppShowsTheChoices(unittest.TestCase):
    def test_a_button_runs_a_request_or_an_act(self):
        swift = (REPO / "extras" / "status" / "app" / "Garrick.swift").read_text(encoding="utf-8")
        self.assertIn('turn.choices = out["choices"] as? [[String: Any]] ?? []', swift)
        self.assertIn("@objc func askChoose(_ sender: NSButton)", swift)
        self.assertIn('if let request = choice["act"] as? [String: Any] {\n\t\t\tact(request)', swift)
        self.assertIn('askSend(request)', swift)
        self.assertIn("row.isHidden = offered.isEmpty && chosen.isEmpty", swift)


class TestUndoOfAMade(manage.ManageCase):
    """scaffold.py's undo reverts a creation too, while it is the zone's last commit (#345)."""

    def run_page(self, **req):
        return manage.pa.act(self.root, dict(req), today=None)

    def test_a_thread_made_by_the_page_is_undone(self):
        self.run_page(verb="new-thread", zone="Work", project="Acme", name="Renewal")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        self.assertEqual("Acme: new thread Renewal", self.git("log", "-1", "--format=%s").stdout.strip())
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("Undone: Acme: new thread Renewal.", r.stdout)
        self.assertFalse((self.work / "Acme" / "Threads" / "Renewal").exists())

    def test_a_project_made_by_the_page_is_undone(self):
        self.run_page(verb="new-project", zone="Work", name="Quarry", party="acme", thread="Plan")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertFalse((self.work / "Quarry").exists())

    def test_it_is_refused_once_anything_else_was_committed(self):
        self.run_page(verb="new-thread", zone="Work", project="Acme", name="Renewal")
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()
        (self.work / "Todo.md").write_text((self.work / "Todo.md").read_text() + "\n")
        self.commit("something else")
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(1, r.returncode)
        self.assertIn("is no longer the last commit", r.stderr)
        self.assertTrue((self.work / "Acme" / "Threads" / "Renewal").is_dir())

    def test_a_commit_that_is_neither_is_still_refused(self):
        head = self.git("rev-parse", "--short", "HEAD").stdout.strip()                        # "Acme set up"
        r = self.scaffold("undo", "--zone", "Work", "--commit", head)
        self.assertEqual(1, r.returncode)
        self.assertIn("is not a rename, a deletion or a new project or thread", r.stderr)


if __name__ == "__main__":
    unittest.main()
