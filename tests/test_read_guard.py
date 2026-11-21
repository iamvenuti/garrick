"""The read guard (#613): what a session may read, from its own zone, across a wall, from the root; warn-only
first, the log, the harnesses, the cost.

    cd tests && python3 -m unittest test_read_guard
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

from read_guard_case import GUARD, REPO, SENTENCE, GuardCase, put  # noqa: E402

ZONE_GUARD = REPO / "extras" / "hooks" / "zone_guard.py"
POINTER = "recall.py search"


class Enforced(GuardCase):
    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "enforce"})

    def refused(self, reply):
        decision, reason = self.decision(reply)
        self.assertEqual("deny", decision)
        self.assertTrue(reason.startswith(SENTENCE), reason)
        return reason

    def test_a_meeting_page_of_another_walled_zone_is_refused_and_names_nothing(self):
        reason = self.refused(self.read(self.root / "Wikis/Meetings/wiki/birch-pricing.md"))
        self.assertEqual(SENTENCE, reason)
        for word in ("birch", "Birch", "pricing", "Personal", "wiki", str(self.root)):
            self.assertNotIn(word, reason)

    def test_a_file_in_another_walled_zone_is_refused(self):
        self.assertEqual(SENTENCE, self.refused(self.read(self.birch / "Notes/secret.md")))

    def test_the_sessions_own_zone_open_zones_and_knowledge_are_read(self):
        for path in (self.acme / "Acme.md", self.root / "Zones/Work/Todo.md", self.root / "Wikis/Meetings/wiki/acme-kickoff.md",
                     self.root / "Wikis/Meetings/wiki/cedar-garden.md", self.cedar / "Cedar.md",
                     self.root / "Wikis/Knowledge/wiki/standard.md", self.root / "System/notes.md",
                     self.acme / "Threads/Kickoff/Kickoff.md"):
            with self.subTest(path=path.name):
                self.assertIsNone(self.read(path))

    def test_a_page_with_no_zone_and_a_knowledge_page_that_names_one_are_refused(self):
        self.refused(self.read(self.root / "Wikis/Meetings/wiki/loose.md"))
        self.refused(self.read(self.root / "Wikis/Knowledge/wiki/owned.md"))

    def test_a_session_in_an_open_zone_reads_open_material_and_no_walled_page(self):
        self.assertIsNone(self.read(self.root / "Wikis/Meetings/wiki/cedar-garden.md", home=self.cedar))
        self.refused(self.read(self.root / "Wikis/Meetings/wiki/acme-kickoff.md", home=self.cedar))
        self.refused(self.read(self.acme / "Acme.md", home=self.cedar))

    def test_the_other_side_of_the_wall_is_refused_too(self):
        self.refused(self.read(self.acme / "Acme.md", home=self.birch))
        self.assertIsNone(self.read(self.birch / "Birch.md", home=self.birch))

    def test_the_agents_files_are_read_from_anywhere(self):
        self.assertIsNone(self.read(self.root / "Zones/Work/AGENTS.md", home=self.birch))
        self.assertIsNone(self.read(self.root / "Wikis/Meetings/AGENTS.md"))

    def test_a_session_at_the_root_or_in_system_reads_everything(self):
        for home in (self.root, self.root / "System"):
            for path in (self.birch / "Notes/secret.md", self.root / "Wikis/Meetings/wiki/birch-pricing.md",
                         self.root / "Wikis/Meetings/wiki/loose.md"):
                with self.subTest(home=home.name, path=path.name):
                    self.assertIsNone(self.read(path, home=home))
            self.assertIsNone(self.call("Grep", {"pattern": "x", "path": str(self.root / "Wikis")}, home=home))
            self.assertIsNone(self.call("Bash", {"command": "cat Wikis/Meetings/wiki/birch-pricing.md"}, home=home))

    def test_a_session_outside_any_workspace_is_never_stopped(self):
        outside = self.root.parent / "elsewhere"
        outside.mkdir()
        self.assertIsNone(self.run_hook({"session_id": "x", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(outside),
                                         "tool_input": {"file_path": str(self.birch / "Notes/secret.md")}}, project_dir=outside))

    def test_a_path_outside_the_workspace_is_read(self):
        scratch = put(self.root.parent / "scratch" / "a.txt", "x")
        self.assertIsNone(self.read(scratch))

    def test_a_link_is_judged_where_it_leads(self):
        link = self.acme / "elsewhere"
        link.symlink_to(self.birch)
        self.refused(self.read(link / "Notes/secret.md"))

    def test_raw_grep_over_the_wikis_is_refused_with_the_pointer(self):
        for path in ("Wikis", "Wikis/Meetings", "Wikis/Meetings/wiki"):
            with self.subTest(path=path):
                reason = self.refused(self.call("Grep", {"pattern": "price", "path": str(self.root / path)}))
                self.assertIn(POINTER, reason)
                self.assertNotIn("Birch", reason)

    def test_glob_over_the_wikis_is_refused_with_the_pointer(self):
        reason = self.refused(self.call("Glob", {"pattern": "Wikis/Meetings/**/*.md", "path": str(self.root)}))
        self.assertIn(POINTER, reason)
        self.refused(self.call("Glob", {"pattern": str(self.root / "Wikis/**/*.md")}))

    def test_grep_from_the_root_of_the_workspace_over_several_zones_is_refused(self):
        self.refused(self.call("Grep", {"pattern": "x", "path": str(self.root)}))
        self.refused(self.call("Grep", {"pattern": "x", "path": str(self.root / "Zones")}))

    def test_grep_and_glob_inside_the_sessions_own_zone_go_ahead(self):
        self.assertIsNone(self.call("Grep", {"pattern": "x", "path": str(self.acme)}))
        self.assertIsNone(self.call("Grep", {"pattern": "x"}))                       # the session's own folder
        self.assertIsNone(self.call("Grep", {"pattern": "x", "path": str(self.root / "Zones/Work")}))
        self.assertIsNone(self.call("Glob", {"pattern": "**/*.md"}))
        self.assertIsNone(self.call("Glob", {"pattern": str(self.acme / "Threads/**/*.md")}))

    def test_grep_in_another_walled_zone_is_refused(self):
        self.refused(self.call("Grep", {"pattern": "x", "path": str(self.birch)}))
        self.refused(self.call("Glob", {"pattern": "**/*.md", "path": str(self.birch)}))

    def test_grep_over_the_knowledge_wiki_goes_ahead(self):
        self.assertIsNone(self.call("Grep", {"pattern": "x", "path": str(self.root / "Wikis/Knowledge")}))

    def test_shell_commands_naming_walled_paths_are_decided_like_reads(self):
        self.refused(self.call("Bash", {"command": "cat '%s'" % (self.root / "Wikis/Meetings/wiki/birch-pricing.md")}))
        self.refused(self.call("Bash", {"command": "grep -r price ../../../Wikis/", }, cwd=self.acme))
        self.refused(self.call("Bash", {"command": "ls %s | head" % (self.birch)}))
        self.refused(self.call("Bash", {"command": "cat Zones/Personal/Birch/Birch.md && echo done"}, cwd=self.root))
        self.refused(self.call("Bash", {"command": "rg x --glob '*.md' Wikis/Meetings/wiki/*"}, cwd=self.root))

    def test_shell_commands_in_the_sessions_own_places_go_ahead(self):
        self.assertIsNone(self.call("Bash", {"command": "cat Acme.md | wc -l"}))
        self.assertIsNone(self.call("Bash", {"command": "git status && ls Threads/"}))
        self.assertIsNone(self.call("Bash", {"command": "python3 %s/System/tools/check.py" % self.root}))

    def test_a_shell_command_that_cannot_be_read_goes_ahead_and_is_logged_as_unread(self):
        self.assertIsNone(self.call("Bash", {"command": "cat $(echo Wikis/Meetings/wiki/birch-pricing.md)"}))
        self.assertIsNone(self.call("Bash", {"command": "cat \"unbalanced"}))
        kinds = [l.get("kind") for l in self.log_lines()]
        self.assertEqual(["unread", "unread"], kinds)
        self.assertEqual({"allow"}, {l["decision"] for l in self.log_lines()})

    def test_any_other_tool_is_left_alone(self):
        self.assertIsNone(self.call("WebFetch", {"url": "https://example.invalid"}))
        self.assertEqual([], self.log_lines())

    def test_a_broken_event_lets_the_call_through_and_logs_the_error(self):
        self.assertIsNone(self.run_hook(None, project_dir=self.acme, raw="not json"))
        self.assertIsNone(self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.acme),
                                         "tool_input": "oops"}, project_dir=self.acme))
        self.assertEqual("error", self.log_lines()[-1]["decision"])

    def test_a_scheduled_job_is_logged_and_never_refused(self):
        reply = self.run_hook({"session_id": "j", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.acme),
                               "tool_input": {"file_path": str(self.birch / "Notes/secret.md")}}, project_dir=self.acme, headless=True)
        self.assertIsNone(reply)
        self.assertEqual("deny", self.log_lines()[-1]["decision"])

    def test_the_guards_folder_inside_the_workspace_is_never_read_by_a_session(self):
        inner = self.root / "System" / "inner-state"
        env_jobs = self.root / "System" / "inner-jobs"
        home = self.acme
        event = {"session_id": "z", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(home),
                 "tool_input": {"file_path": str(self.root / "System" / "garrick-read-guard" / "read-guard.log")}}
        # GARRICK_JOBS_DIR inside System/ puts the guard's folder at System/garrick-read-guard
        done = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True,
                              env=dict(self.env(home), GARRICK_JOBS_DIR=str(self.root / "System" / "jobs")), timeout=60)
        self.assertEqual(0, done.returncode)
        reply = json.loads(done.stdout)
        self.assertEqual(SENTENCE, reply["hookSpecificOutput"]["permissionDecisionReason"])
        del inner, env_jobs

    # the recorded scope

    def test_the_scope_recorded_at_session_start_decides_wherever_the_call_is_made_from(self):
        self.start(self.acme)
        record = json.loads((self.state / "sessions" / "s1.json").read_text())
        self.assertEqual({"kind": "zone", "zone": "Work", "project": "Acme", "parties": ["acme"]},
                         {k: record[k] for k in ("kind", "zone", "project", "parties")})
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.root),
                 "tool_input": {"file_path": str(self.birch / "Notes/secret.md")}}
        reply = self.run_hook(event)                                  # no CLAUDE_PROJECT_DIR, working folder is the root
        self.assertEqual("deny", self.decision(reply)[0])

    def test_without_a_record_the_working_folder_decides(self):
        event = {"session_id": "none", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.acme),
                 "tool_input": {"file_path": str(self.birch / "Notes/secret.md")}}
        self.assertEqual("deny", self.decision(self.run_hook(event))[0])
        event["cwd"] = str(self.root)
        self.assertIsNone(self.run_hook(event))                       # a session at the root keeps full read

    def test_the_record_is_outside_the_workspace_and_names_no_walled_material(self):
        self.start(self.acme)
        self.assertFalse(str(self.state).startswith(str(self.root)))
        text = (self.state / "sessions" / "s1.json").read_text()
        for word in ("Birch", "birch", "Personal"):
            self.assertNotIn(word, text)

    # asking

    def test_across_a_wall_the_user_asked_for_raises_one_permission_prompt(self):
        self.settings(**{"read-guard": "enforce", "read-guard-cross-zone": "ask"})
        decision, reason = self.decision(self.read(self.birch / "Notes/secret.md"))
        self.assertEqual("ask", decision)
        self.assertEqual(SENTENCE, reason)

    def test_asking_does_not_cover_a_page_with_no_zone(self):
        self.settings(**{"read-guard": "enforce", "read-guard-cross-zone": "ask"})
        self.assertEqual("deny", self.decision(self.read(self.root / "Wikis/Meetings/wiki/loose.md"))[0])

    def test_codex_cannot_ask_so_it_refuses_once_and_lets_the_same_path_through_the_second_time(self):
        self.settings(**{"read-guard": "enforce", "read-guard-cross-zone": "ask"})
        event = {"session_id": "cx", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.acme),
                 "tool_input": {"command": "cat %s" % (self.birch / "Notes/secret.md")}}
        first = self.run_hook(event)                                  # no CLAUDE_PROJECT_DIR: Codex
        decision, reason = self.decision(first)
        self.assertEqual("deny", decision)
        self.assertTrue(reason.startswith(SENTENCE))
        self.assertIsNone(self.run_hook(event))
        other = dict(event, tool_input={"command": "cat %s" % (self.birch / "Birch.md")})
        self.assertEqual("deny", self.decision(self.run_hook(other))[0])

    # switch

    def test_anything_but_enforce_is_warn(self):
        for value in ("warn", "ENFORCE", True, 1, None, ["enforce"]):
            with self.subTest(value=value):
                self.settings(**{"read-guard": value})
                self.assertIsNone(self.read(self.birch / "Notes/secret.md"))
        (self.root / "System" / "garrick-settings.json").write_text("{not json")
        self.assertIsNone(self.read(self.birch / "Notes/secret.md"))
        (self.root / "System" / "garrick-settings.json").unlink()
        self.assertIsNone(self.read(self.birch / "Notes/secret.md"))


class WarnOnly(GuardCase):
    """The template's default: nothing is refused, every would-be refusal is logged."""

    def test_nothing_is_refused_and_each_would_be_refusal_is_logged(self):
        reads = [self.birch / "Notes/secret.md", self.root / "Wikis/Meetings/wiki/birch-pricing.md", self.acme / "Acme.md"]
        for path in reads:
            self.assertIsNone(self.read(path))
        self.assertIsNone(self.call("Grep", {"pattern": "x", "path": str(self.root / "Wikis")}))
        self.assertIsNone(self.call("Bash", {"command": "cat Zones/Personal/Birch/Birch.md"}, cwd=self.root))
        got = self.log_lines()
        self.assertEqual(["deny", "deny", "allow", "deny", "deny"], [l["decision"] for l in got])
        self.assertEqual(["Read", "Read", "Read", "Grep", "Bash"], [l["tool"] for l in got])
        self.assertEqual({"Work"}, {l["zone"] for l in got})

    def test_the_log_holds_no_path_party_title_or_count(self):
        self.read(self.birch / "Notes/secret.md")
        self.read(self.root / "Wikis/Meetings/wiki/birch-pricing.md")
        self.call("Grep", {"pattern": "birch", "path": str(self.root / "Wikis")})
        text = self.log_text()
        self.assertTrue(text)
        for word in ("Birch", "birch", "secret", "pricing", "Personal", str(self.root), "Notes", "Wikis", "Meetings"):
            self.assertNotIn(word, text)
        for line in self.log_lines():
            self.assertEqual({"t", "tool", "decision", "zone", "id", "kind"} - {"kind"} | ({"kind"} & set(line)), set(line))
            self.assertRegex(line["id"], r"^[0-9a-f]{12}$")

    def test_a_root_session_is_not_logged(self):
        self.read(self.birch / "Notes/secret.md", home=self.root)
        self.assertEqual([], self.log_lines())

    def test_the_log_stays_out_of_the_workspace(self):
        self.read(self.birch / "Notes/secret.md")
        self.assertTrue((self.state / "read-guard.log").is_file())
        self.assertFalse(str(self.state).startswith(str(self.root)))

    def test_a_guard_folder_inside_the_workspace_is_logged_and_allowed_in_warn(self):
        event = {"session_id": "z", "hook_event_name": "PreToolUse", "tool_name": "Grep", "cwd": str(self.acme),
                 "tool_input": {"pattern": "x", "path": str(self.root / "System" / "garrick-read-guard")}}
        done = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True,
                              env=dict(self.env(self.acme), GARRICK_JOBS_DIR=str(self.root / "System" / "jobs")), timeout=60)
        self.assertEqual("", done.stdout.strip())
        lines = (self.root / "System" / "garrick-read-guard" / "read-guard.log").read_text().splitlines()
        self.assertEqual("folder", json.loads(lines[-1])["kind"])


class Knowledge(GuardCase):
    """Fix round W3, C9: the Knowledge wiki crosses every wall, folders and missing paths included; a file that is no
    readable page is no one's."""

    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "enforce"})
        (self.root / "Wikis/Knowledge/raw").mkdir()
        (self.root / "Wikis/Knowledge/wiki/binary.pdf").write_bytes(b"%PDF\0\1\2 not text")
        (self.root / "Wikis/Knowledge/wiki/huge.md").write_text("x" * 1_600_000)

    def test_a_knowledge_folder_is_read_by_every_scope(self):
        for home in (self.acme, self.birch, self.cedar):
            for tool, given in (("Glob", {"pattern": "*.md", "path": str(self.root / "Wikis/Knowledge/wiki")}),
                                ("Grep", {"pattern": "x", "path": str(self.root / "Wikis/Knowledge/raw")}),
                                ("Grep", {"pattern": "x", "path": str(self.root / "Wikis/Knowledge")}),
                                ("Bash", {"command": "ls " + str(self.root / "Wikis/Knowledge/wiki")}),
                                ("Read", {"file_path": str(self.root / "Wikis/Knowledge/wiki/not-yet.md")})):
                with self.subTest(home=home.name, tool=tool, given=given):
                    self.assertIsNone(self.call(tool, given, home))

    def test_a_file_that_cannot_be_read_as_text_or_is_over_the_cap_is_refused(self):
        for name in ("binary.pdf", "huge.md"):
            with self.subTest(name=name):
                self.assertEqual("deny", self.decision(self.read(self.root / "Wikis/Knowledge/wiki" / name))[0])
        self.assertEqual("deny", self.decision(self.call("Bash", {"command": "cat " + str(self.root / "Wikis/Knowledge/wiki/huge.md")}))[0])

    def test_a_knowledge_page_that_names_a_zone_stays_refused_and_a_plain_one_is_read(self):
        self.assertEqual("deny", self.decision(self.read(self.root / "Wikis/Knowledge/wiki/owned.md"))[0])
        self.assertIsNone(self.read(self.root / "Wikis/Knowledge/wiki/standard.md"))

    def test_in_warn_only_a_refused_file_is_logged_and_read(self):
        self.settings(**{"read-guard": "warn"})
        self.assertIsNone(self.read(self.root / "Wikis/Knowledge/wiki/binary.pdf"))
        self.assertEqual("deny", self.log_lines()[-1]["decision"])


class Links(GuardCase):
    """Fix round S3: a link in a walled zone that leads outside the workspace is judged by where it sits too."""

    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "enforce"})
        self.shared = Path(os.path.realpath(self.tmp.name)) / "shared-library"
        put(self.shared / "plan.txt", "Plan\n")
        (self.root / "Zones/Personal/.shared").mkdir()
        (self.root / "Zones/Personal/.shared/lib").symlink_to(self.shared)
        (self.root / "Zones/Work/Acme/shared").symlink_to(self.shared)

    def test_a_link_in_another_walled_zone_is_refused_though_it_leads_outside(self):
        for tool, given in (("Read", {"file_path": str(self.root / "Zones/Personal/.shared/lib/plan.txt")}),
                            ("Grep", {"pattern": "x", "path": str(self.root / "Zones/Personal/.shared/lib")}),
                            ("Glob", {"pattern": "Zones/Personal/.shared/lib/*.txt", "path": str(self.root)}),
                            ("Bash", {"command": "cat '%s'" % (self.root / "Zones/Personal/.shared/lib/plan.txt")})):
            with self.subTest(tool=tool):
                self.assertEqual("deny", self.decision(self.call(tool, given))[0])

    def test_a_link_in_the_sessions_own_zone_leading_outside_is_read(self):
        self.assertIsNone(self.read(self.acme / "shared" / "plan.txt"))
        self.assertIsNone(self.read(self.shared / "plan.txt"))             # the real place, outside the workspace

    def test_the_other_zone_reads_its_own_link(self):
        self.assertIsNone(self.read(self.root / "Zones/Personal/.shared/lib/plan.txt", home=self.birch))

    def test_in_warn_only_the_link_is_logged_and_read(self):
        self.settings(**{"read-guard": "warn"})
        self.assertIsNone(self.read(self.root / "Zones/Personal/.shared/lib/plan.txt"))
        self.assertEqual("deny", self.log_lines()[-1]["decision"])


class Globs(GuardCase):
    """Fix round S2: a brace group or a wildcard before the first slash is judged by each literal prefix."""

    def setUp(self):
        super().setUp()
        self.settings(**{"read-guard": "enforce"})

    def refused(self, tool, given, home=None):
        decision, reason = self.decision(self.call(tool, given, home))
        self.assertEqual("deny", decision, given)
        self.assertTrue(reason.startswith(SENTENCE))
        return reason

    def test_a_leading_brace_group_is_judged_by_each_of_its_prefixes(self):
        self.refused("Glob", {"pattern": "{Zones/Work,Zones/Personal}/**/*.md", "path": str(self.root)}, self.acme)
        self.refused("Glob", {"pattern": "{../../Personal/Birch,.}/Notes/*.md"}, self.acme)
        self.refused("Glob", {"pattern": "{x,{../../Personal/Birch,y}}/**"}, self.acme)
        self.refused("Glob", {"pattern": "../../Personal/Birch/{Notes,Other}/*.md"}, self.acme)
        self.assertIsNone(self.call("Glob", {"pattern": "{Threads,Sources}/**/*.md"}))
        self.assertIsNone(self.call("Glob", {"pattern": "{Threads,.}/**/*.md"}))

    def test_a_pattern_with_a_wildcard_before_the_first_slash_is_a_span_of_its_base(self):
        reason = self.refused("Glob", {"pattern": "*/Birch/**/*.md", "path": str(self.root / "Zones")}, self.acme)
        self.assertIn(POINTER, reason)
        self.refused("Glob", {"pattern": "{a,b}*/**/*.md", "path": str(self.root)}, self.acme)
        self.refused("Glob", {"pattern": "*/wiki/*.md", "path": str(self.root / "Wikis")}, self.acme)
        self.assertIsNone(self.call("Glob", {"pattern": "*/*.md"}))              # based in the session's own folder

    def test_a_group_with_too_many_expansions_is_cut_at_the_brace(self):
        many = "{" + ",".join("d%d" % i for i in range(80)) + "}/*.md"
        self.refused("Glob", {"pattern": many, "path": str(self.root / "Zones")}, self.acme)
        self.assertIsNone(self.call("Glob", {"pattern": many}))
        self.refused("Glob", {"pattern": "{Zones/Work", "path": str(self.root)}, self.acme)       # never closed

    def test_a_grep_glob_is_judged_the_same_way(self):
        self.refused("Grep", {"pattern": "x", "glob": "{../../Personal/Birch,.}/**/*.md"}, self.acme)
        self.assertIsNone(self.call("Grep", {"pattern": "x", "glob": "{Threads,Sources}/**/*.md"}))
        self.assertIsNone(self.call("Grep", {"pattern": "x", "glob": "*.md"}))


class GuardFolder(GuardCase):
    """Fix round S1: the guard's own folder is never read or written by a session, wherever it sits."""

    def prepare(self, mode="enforce"):
        self.settings(**{"read-guard": mode})
        self.start(self.acme)
        self.assertTrue((self.state / "sessions" / "s1.json").is_file())

    def test_a_read_of_the_folder_is_refused_in_every_form_when_enforcing(self):
        self.prepare()
        record = self.state / "sessions" / "s1.json"
        calls = (("Read", {"file_path": str(record)}), ("Grep", {"pattern": "x", "path": str(self.state)}),
                 ("Glob", {"pattern": "*.json", "path": str(self.state / "sessions")}),
                 ("Glob", {"pattern": str(self.state) + "/**/*.log"}),
                 ("Bash", {"command": "cat " + str(self.state / "read-guard.log")}),
                 ("Bash", {"command": "ls " + str(self.state / "sessions") + "/*"}))
        for tool, given in calls:
            with self.subTest(tool=tool, given=given):
                decision, reason = self.decision(self.call(tool, given))
                self.assertEqual(("deny", SENTENCE), (decision, reason))

    def test_a_root_session_is_refused_too(self):
        self.prepare()
        self.start(self.root)
        self.assertEqual("deny", self.decision(self.call("Read", {"file_path": str(self.state / "read-guard.log")}, home=self.root))[0])
        self.assertIsNone(self.call("Read", {"file_path": str(self.root / "System/notes.md")}, home=self.root))

    def test_in_warn_only_the_read_is_logged_and_allowed(self):
        self.prepare("warn")
        self.assertIsNone(self.call("Read", {"file_path": str(self.state / "sessions" / "s1.json")}))
        last = self.log_lines()[-1]
        self.assertEqual(("deny", "folder"), (last["decision"], last["kind"]))
        self.assertNotIn("sessions", self.log_text())

    def test_a_scheduled_job_is_logged_and_never_refused(self):
        self.prepare()
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": str(self.acme),
                 "tool_input": {"file_path": str(self.state / "read-guard.log")}}
        self.assertIsNone(self.run_hook(event, project_dir=self.acme, headless=True))

    def write(self, path, tool="Write", home=None, headless=False):
        home = self.root if home is None else home
        event = {"session_id": "w", "hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(home),
                 "tool_input": {"file_path": str(path), "content": "{}"}}
        env = self.env(home, headless)
        done = subprocess.run([sys.executable, str(ZONE_GUARD)], input=json.dumps(event), capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(0, done.returncode, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_a_write_into_the_folder_is_refused_in_every_mode_and_from_every_home(self):
        record = self.state / "sessions" / "s1.json"
        for home in (self.acme, self.root, self.root / "System"):
            for tool in ("Write", "Edit"):
                with self.subTest(home=home, tool=tool):
                    reply = self.write(record, tool, home)
                    self.assertEqual("deny", reply["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual("deny", self.write(self.state / "read-guard.log", headless=True)["hookSpecificOutput"]["permissionDecision"])
        self.assertIsNone(self.write(self.root / "System" / "notes.md", home=self.root))
        self.assertIsNone(self.write(self.state.parent / "garrick-read-guard-not" / "x", home=self.root))

    def test_the_two_guards_agree_on_where_the_folder_is(self):
        import importlib.util
        from unittest import mock
        tools = str(REPO / "template" / "System" / "tools")
        sys.path.insert(0, tools)
        try:
            import garrick_lib
        finally:
            sys.path.remove(tools)
        spec = importlib.util.spec_from_file_location("garrick_zone_guard_folder", str(ZONE_GUARD))
        zg = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = zg
        spec.loader.exec_module(zg)
        base = os.path.realpath(str(self.home))
        for jobs in (None, os.path.join(base, "somewhere", "jobs"), os.path.join(base, "jobs") + os.sep):
            for platform in ("darwin", "linux"):
                env = {"HOME": base}
                if jobs:
                    env["GARRICK_JOBS_DIR"] = jobs
                with self.subTest(jobs=jobs, platform=platform), \
                        mock.patch.dict(os.environ, env), mock.patch.object(sys, "platform", platform):
                    os.environ.pop("GARRICK_JOBS_DIR", None) if not jobs else None
                    folder = os.path.realpath(str(garrick_lib.read_guard_dir()))
                    inside_it = os.path.join(folder, "sessions", "s1.json")
                    outside_it = folder + "-not"
                    self.assertEqual([inside_it], zg.read_guard_edits([inside_it, outside_it, base]))


class Cost(GuardCase):
    def test_the_time_one_call_takes(self):
        self.settings(**{"read-guard": "enforce"})
        path = self.acme / "Acme.md"
        self.read(path)
        start = time.perf_counter()
        for _ in range(10):
            self.read(path)
        each = (time.perf_counter() - start) / 10
        sys.stderr.write("\nread guard: %.0f ms per read call (Python start included)\n" % (each * 1000))
        self.assertLess(each, 1.0)


class Registration(GuardCase):
    def hooks(self, assistant, hooks):
        folder = self.home / assistant
        folder.mkdir(exist_ok=True)
        name = "settings.json" if assistant == ".claude" else "hooks.json"
        (folder / name).write_text(json.dumps({"hooks": hooks}))

    def command(self):
        return [{"type": "command", "command": "python3 %s" % GUARD}]

    def run_check(self, script):
        done = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True,
                              env=self.env(), timeout=30)
        return done.returncode, done.stdout

    def full_claude(self):
        return {"SessionStart": [{"hooks": self.command()}],
                "PreToolUse": [{"matcher": "Read|Grep|Glob|Bash", "hooks": self.command()}],
                "PostToolUse": [{"matcher": "mcp__.*", "hooks": self.command()}]}

    def test_check_names_what_is_missing(self):
        self.hooks(".claude", {"PreToolUse": [{"matcher": "Read|Grep", "hooks": self.command()}]})
        code, out = self.run_check(GUARD)
        self.assertEqual(1, code)
        self.assertIn("Glob", out)
        self.assertIn("SessionStart", out)

    def test_check_passes_for_a_full_registration(self):
        self.hooks(".claude", self.full_claude())
        code, out = self.run_check(GUARD)
        self.assertEqual(0, code, out)
        self.assertIn("the read guard is registered", out)

    def test_codex_needs_the_session_start_and_the_shell_hooks_and_no_connector_hook(self):
        self.hooks(".codex", {"SessionStart": [{"hooks": self.command()}],
                              "PreToolUse": [{"matcher": "Bash", "hooks": self.command()}]})
        code, out = self.run_check(GUARD)
        self.assertEqual(0, code, out)

    def test_the_zone_guards_check_reports_the_read_guard_too(self):
        zone = [{"type": "command", "command": "python3 %s" % ZONE_GUARD}]
        tools = "Edit|Write|MultiEdit|NotebookEdit"
        hooks = self.full_claude()
        hooks["PreToolUse"].append({"matcher": tools, "hooks": zone})
        hooks["PostToolUse"].append({"matcher": tools, "hooks": zone})
        self.hooks(".claude", hooks)
        code, out = self.run_check(ZONE_GUARD)
        self.assertEqual(0, code, out)
        self.assertIn("zone guard is registered", out)
        self.assertIn("read guard is registered", out)

    def test_the_zone_guards_check_says_so_when_the_read_guard_is_not_there_and_keeps_its_exit_code(self):
        zone = [{"type": "command", "command": "python3 %s" % ZONE_GUARD}]
        tools = "Edit|Write|MultiEdit|NotebookEdit"
        self.hooks(".claude", {"PreToolUse": [{"matcher": tools, "hooks": zone}], "PostToolUse": [{"matcher": tools, "hooks": zone}]})
        code, out = self.run_check(ZONE_GUARD)
        self.assertEqual(0, code, out)
        self.assertIn("read guard is not registered", out)


if __name__ == "__main__":
    unittest.main()
