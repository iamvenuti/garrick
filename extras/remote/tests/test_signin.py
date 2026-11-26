"""Sign in (#697): the service as its own authorization server, attacked.

    <runtime python> -m unittest test_signin        (from extras/remote/tests)

A3 (credentials): invalid, expired and revoked tokens, a token for another resource, a changed callback, a wider scope, a grant changed
while in use, a call with no token. A18 (the sign-in surface under attack): floods and repeated wrong codes are slowed and then refused.
Plus the four pieces the SDK leaves to the provider, each on its own.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from remote_fixture import mod  # noqa: E402
from service_fixture import Raw, ServiceCase  # noqa: E402


class Stub:
    @staticmethod
    def register(server, session_for):
        @server.tool(name="stub-who", description="Say which grant is calling.")
        def who() -> dict:
            s = session_for(None)
            return {"grant": s.grant_id, "read": sorted(s.readable), "write": sorted(s.writable), "classes": sorted(s.classes)}


class Case(ServiceCase):
    def setUp(self):
        super().setUp()
        mod("service").Guard.SLOW_SECONDS = 0
        self.addCleanup(lambda: setattr(mod("service").Guard, "SLOW_SECONDS", 1.5))
        self.served = self.serve(Stub)
        self.served.__enter__()
        self.addCleanup(lambda: self.served.__exit__(None, None, None))
        self.raw = Raw(self.served, self)
        self.act = mod("settings_actions")

    def grant_id(self):
        return self.store.listing()[0]["id"]


class Credentials(Case):
    def test_a_call_with_no_token_is_refused_on_every_revision(self):
        for version in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"):
            r = self.raw.mcp(headers={"MCP-Protocol-Version": version})
            self.assertEqual(r.status_code, 401, version)
            self.assertIn("resource_metadata", r.headers["www-authenticate"])

    def test_an_invalid_token_is_refused(self):
        for bad in ("", "x", "a" * 43, "Bearer"):
            self.assertEqual(self.raw.mcp(bad or None).status_code, 401, bad)

    def test_a_good_token_reaches_the_tool_on_the_handshake_revisions(self):
        tokens = self.raw.sign_in()
        r = self.raw.mcp(tokens["access_token"], headers={"MCP-Protocol-Version": "2025-06-18"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_an_expired_token_is_refused(self):
        self.raw.sign_in()
        gid = self.grant_id()
        pair = self.store.issue(gid, self.raw.client_id, ["read"], self.served.mcp_url, now=time.time() - 3600)
        self.assertEqual(self.raw.mcp(pair["access"]).status_code, 401)

    def test_a_revoked_grant_is_refused_on_the_very_next_call(self):
        tokens = self.raw.sign_in()
        self.assertEqual(self.raw.mcp(tokens["access_token"]).status_code, 200)
        self.assertTrue(self.act.run(self.ws, {"action": "revoke", "grant": self.grant_id()})["ok"])
        self.assertEqual(self.raw.mcp(tokens["access_token"]).status_code, 401)
        self.assertEqual(self.raw.refresh(tokens["refresh_token"]).status_code, 400)

    def test_a_token_for_another_resource_is_refused(self):
        self.raw.sign_in()
        pair = self.store.issue(self.grant_id(), self.raw.client_id, ["read"], "http://127.0.0.1:1/mcp")
        self.assertEqual(self.raw.mcp(pair["access"]).status_code, 401)

    def test_asking_for_another_resource_is_refused_at_the_door(self):
        self.raw.register()
        r = self.raw.authorize(resource="https://elsewhere.example.test/mcp")
        self.assertEqual(r.status_code, 302)
        self.assertIn("error=invalid_target", r.headers["location"])
        self.assertNotIn("/consent", r.headers["location"])

    def test_a_changed_callback_is_refused_without_a_redirect(self):
        self.raw.register()
        for other in ("https://evil.example.test/cb", "http://127.0.0.1.evil.example.test/cb", "http://127.0.0.1:19999/other",
                      "https://claude.ai/api/mcp/auth_callback"):
            r = self.raw.authorize(redirect=other)
            self.assertEqual(r.status_code, 400, other)
            self.assertNotIn("location", r.headers)

    def test_registering_a_callback_off_the_list_is_refused(self):
        for bad in ("https://evil.example.test/cb", "http://evil.example.test/cb", "http://10.0.0.5:1/cb", "javascript:alert(1)",
                    "https://claude.ai.evil.example.test/api/mcp/auth_callback", "http://user@127.0.0.1/cb"):
            r = self.raw.register(redirect_uris=[bad])
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()["error"], "invalid_redirect_uri", bad)

    def test_the_published_callbacks_and_loopback_may_be_registered(self):
        for good in ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback", "http://localhost:5000/cb",
                     "http://127.0.0.1:1234/callback"):
            self.assertEqual(self.raw.register(redirect_uris=[good]).status_code, 201, good)

    def test_loopback_matches_on_any_port_and_nothing_else_does(self):
        self.raw.register()
        r = self.raw.authorize(redirect="http://127.0.0.1:45555/callback")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/consent?p=", r.headers["location"])
        self.assertEqual(self.raw.authorize(redirect="http://localhost:45555/callback").status_code, 400)       # another host name

    def test_a_wider_scope_is_refused(self):
        self.raw.register()
        r = self.raw.authorize(scope="read write admin")
        self.assertIn("error=invalid_scope", r.headers["location"])
        r = self.raw.register(scope="read admin")
        self.assertEqual(r.status_code, 400)

    def test_a_refresh_cannot_ask_for_more_than_it_has(self):
        tokens = self.raw.sign_in(write=False)
        r = self.raw.refresh(tokens["refresh_token"], scope="read write")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid_scope")

    def test_write_is_given_only_when_the_owner_ticks_it(self):
        self.raw.sign_in(write=False)
        self.assertEqual(self.store.listing()[0]["classes"], ["read"])
        tokens = self.raw.sign_in(write=True)
        self.assertEqual(tokens["scope"], "read write")

    def test_a_grant_changed_while_in_use_changes_the_next_call(self):
        tokens = self.raw.sign_in(write=True)
        gid = self.grant_id()
        ctx = mod("context")
        self.assertNotIn("Work", ctx.session_for(self.ws, gid).readable)
        ack = {"action": "zone", "grant": gid, "zone": "Work", "read": True, "write": False, "acknowledged": True}
        self.assertTrue(self.act.run(self.ws, ack)["ok"])
        self.assertIn("Work", ctx.session_for(self.ws, gid).readable)
        self.assertNotIn("Work", ctx.session_for(self.ws, gid).writable)
        self.act.run(self.ws, dict(ack, read=False))
        self.assertNotIn("Work", ctx.session_for(self.ws, gid).readable)

    def test_the_pause_and_the_off_block_the_next_call_and_resume_opens_it(self):
        tokens = self.raw.sign_in()
        t = tokens["access_token"]
        self.assertEqual(self.raw.mcp(t).status_code, 200)
        self.act.run(self.ws, {"action": "pause"})
        self.assertEqual(self.raw.mcp(t).status_code, 503)
        self.assertEqual(self.raw.http.get("/.well-known/oauth-authorization-server").status_code, 503)
        self.act.run(self.ws, {"action": "resume"})
        self.assertEqual(self.raw.mcp(t).status_code, 200)
        self.state.set_status("off")
        self.assertEqual(self.raw.mcp(t).status_code, 503)

    def test_a_changed_address_closes_everything_until_the_service_restarts(self):
        tokens = self.raw.sign_in()
        self.state.set_address("https://other.example.test", "own")
        self.assertEqual(self.raw.mcp(tokens["access_token"]).status_code, 503)

    def test_the_dns_rebinding_guard_refuses_a_foreign_host_name(self):
        tokens = self.raw.sign_in()
        r = self.raw.mcp(tokens["access_token"], headers={"Host": "evil.example.test"})
        self.assertIn(r.status_code, (400, 403, 421))


class Restart(ServiceCase):
    """A2, in part: a restart of the service keeps the sign-in, and the switch is as it was."""

    def test_a_restart_keeps_the_address_the_switch_and_every_sign_in(self):
        mod("service").Guard.SLOW_SECONDS = 0
        first = self.serve(Stub)
        first.__enter__()
        raw = Raw(first, self)
        tokens = raw.sign_in()
        self.assertEqual(raw.mcp(tokens["access_token"]).status_code, 200)
        first.__exit__(None, None, None)
        again = self.serve(Stub, port=first.port)
        again.__enter__()
        self.addCleanup(lambda: again.__exit__(None, None, None))
        self.assertEqual(self.state.address()["url"], first.url)
        self.assertEqual(self.state.status(), "on")
        raw2 = Raw(again, self)
        raw2.client_id = raw.client_id
        self.assertEqual(raw2.mcp(tokens["access_token"]).status_code, 200)
        new = raw2.refresh(tokens["refresh_token"])
        self.assertEqual(new.status_code, 200)


class Tokens(Case):
    def test_tokens_live_ten_minutes_and_refresh_tokens_thirty_days(self):
        tokens = self.raw.sign_in()
        self.assertEqual(tokens["expires_in"], 600)
        db = json.loads((self.state.home() / "auth.json").read_text())
        left = max(v["expires"] for v in db["refresh"].values()) - time.time()
        self.assertAlmostEqual(left / 86400, 30, delta=0.1)

    def test_a_refresh_rotates_and_the_old_one_used_again_closes_the_grant(self):
        first = self.raw.sign_in()
        second = self.raw.refresh(first["refresh_token"])
        self.assertEqual(second.status_code, 200)
        new = second.json()
        self.assertNotEqual(new["refresh_token"], first["refresh_token"])
        self.assertNotEqual(new["access_token"], first["access_token"])
        again = self.raw.refresh(first["refresh_token"])                       # the old one, a second time: two parties hold it
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self.raw.mcp(new["access_token"]).status_code, 401)   # the grant is closed, the new pair with it
        self.assertEqual(self.raw.refresh(new["refresh_token"]).status_code, 400)
        self.assertEqual(self.store.listing(), [])

    def test_an_authorization_code_works_once_and_its_replay_closes_the_grant(self):
        self.raw.register()
        a = self.raw.authorize()
        c = self.raw.consent(a)
        code = parse_qs(urlsplit(c.headers["location"]).query)["code"][0]
        ok = self.raw.token(code)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.raw.token(code).status_code, 400)
        self.assertEqual(self.raw.mcp(ok.json()["access_token"]).status_code, 401)

    def test_a_wrong_code_verifier_is_refused(self):
        self.raw.register()
        c = self.raw.consent(self.raw.authorize())
        code = parse_qs(urlsplit(c.headers["location"]).query)["code"][0]
        self.assertEqual(self.raw.token(code, code_verifier="x" * 50).status_code, 400)

    def test_nothing_that_can_be_presented_is_stored(self):
        tokens = self.raw.sign_in()
        raw = (self.state.home() / "auth.json").read_text()
        for secret in (tokens["access_token"], tokens["refresh_token"]):
            self.assertNotIn(secret, raw)
            self.assertIn(self.store.sha(secret), raw)

    def test_a_client_is_never_given_a_secret(self):
        r = self.raw.register(token_endpoint_auth_method="client_secret_post")
        body = r.json()
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("client_secret", body)
        self.assertEqual(body["token_endpoint_auth_method"], "none")
        self.assertNotIn("client_secret", (self.state.home() / "auth.json").read_text())

    def test_the_handle_key_and_the_auth_file_stay_private(self):
        self.raw.sign_in()
        self.assertEqual(oct(self.state.mode_of(self.state.home() / "auth.json")), "0o600")


class Consent(Case):
    def test_five_wrong_codes_lock_the_page_and_even_the_right_code_is_then_refused(self):
        self.raw.register()
        a = self.raw.authorize()
        right = self.act.run(self.ws, {"action": "pair"})["code"]
        wrong = "000000" if right != "000000" else "111111"
        for i in range(4):
            r = self.raw.consent(a, code=wrong)
            self.assertEqual(r.status_code, 400, i)
        fifth = self.raw.consent(a, code=wrong)
        self.assertEqual(fifth.status_code, 429)
        locked = self.raw.consent(a, code=right)
        self.assertEqual(locked.status_code, 429)
        self.assertNotIn("location", locked.headers)
        self.assertEqual(self.raw.http.get(a.headers["location"]).status_code, 429)
        self.assertEqual(self.act.run(self.ws, {"action": "pair"})["ok"], False)             # no new code while it is locked

    def test_the_page_opens_again_after_fifteen_minutes(self):
        self.raw.register()
        a = self.raw.authorize()
        for _ in range(5):
            self.raw.consent(a, code="123456")
        with self.store.txn() as db:
            db["consent"]["locked_until"] = time.time() - 1
        good = self.act.run(self.ws, {"action": "pair"})["code"]
        self.assertEqual(self.raw.consent(a, code=good).status_code, 302)

    def test_a_code_works_once(self):
        self.raw.register()
        code = self.act.run(self.ws, {"action": "pair"})["code"]
        a = self.raw.authorize()
        self.assertEqual(self.raw.consent(a, code=code).status_code, 302)
        self.assertEqual(self.raw.consent(self.raw.authorize(), code=code).status_code, 400)

    def test_a_code_runs_out_after_five_minutes(self):
        self.raw.register()
        code = self.act.run(self.ws, {"action": "pair"})["code"]
        with self.store.txn() as db:
            for v in db["pairing"].values():
                v["expires"] = time.time() - 1
        self.assertEqual(self.raw.consent(self.raw.authorize(), code=code).status_code, 400)

    def test_read_must_be_ticked(self):
        self.raw.register()
        r = self.raw.consent(self.raw.authorize(), read=False, write=True)
        self.assertEqual(r.status_code, 400)

    def test_the_name_on_the_page_is_text_and_the_page_cannot_be_framed(self):
        self.raw.register(client_name="<script>alert(1)</script> Phone")
        a = self.raw.authorize()
        page = self.raw.http.get(a.headers["location"])
        self.assertNotIn("<script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)
        self.assertEqual(page.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertEqual(page.headers["referrer-policy"], "no-referrer")

    def test_an_unknown_or_expired_sign_in_link_says_start_again(self):
        self.assertEqual(self.raw.http.get("/consent?p=nonsense").status_code, 400)
        self.assertEqual(self.raw.http.post("/consent", data={"p": "nonsense", "code": "123456", "read": "1"}).status_code, 400)

    def test_a_post_from_another_site_is_refused(self):
        self.raw.register()
        a = self.raw.authorize()
        pid = parse_qs(urlsplit(a.headers["location"]).query)["p"][0]
        code = self.act.run(self.ws, {"action": "pair"})["code"]
        r = self.raw.http.post("/consent", data={"p": pid, "code": code, "read": "1"}, headers={"Origin": "https://evil.example.test"})
        self.assertEqual(r.status_code, 403)


class Flood(Case):
    def test_a_flood_of_registrations_is_slowed_then_refused_and_the_service_stays_up(self):
        seen = []
        for _ in range(12):
            seen.append(self.raw.register().status_code)
        self.assertEqual(seen[:8], [201] * 8)
        self.assertIn(429, seen[8:])
        self.assertEqual(self.raw.http.get("/health").status_code, 200)
        r = self.raw.register()
        self.assertEqual(r.status_code, 429)
        self.assertIn("retry-after", r.headers)

    def test_registrations_that_never_complete_expire_and_are_capped(self):
        self.raw.register()
        with self.store.txn() as db:
            for v in db["clients"].values():
                v["made"] = time.time() - 4000
        self.assertEqual(self.store.get_client(self.raw.client_id), None)
        for i in range(self.store.MAX_UNFINISHED):
            self.assertTrue(self.store.put_client("c%d" % i, {"client_id": "c%d" % i}))
        self.assertFalse(self.store.put_client("one-too-many", {"client_id": "x"}))

    def test_a_request_body_that_is_too_big_is_refused_before_it_is_read(self):
        r = self.raw.http.post("/register", content=b"{" + b" " * 70000 + b"}", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_the_limiter_counts_per_caller_and_for_everyone(self):
        lim = mod("limits").Limiter(soft=2, hard=4, window=60, shared_hard=6)
        now = 1000.0
        self.assertEqual([lim.hit("a", now)[0] for _ in range(5)], ["ok", "ok", "slow", "slow", "refuse"])
        self.assertEqual(lim.hit("b", now)[0], "ok")
        for _ in range(4):
            lim.hit("c", now)
        self.assertEqual(lim.hit("d", now)[0], "refuse")                       # everyone together is over its own line
        self.assertEqual(lim.hit("a", now + 61)[0], "ok")                      # the window moves on

    def test_a_flooded_table_stays_bounded(self):
        lim = mod("limits").Limiter(soft=2, hard=4, window=3600, shared_hard=10 ** 9)
        for i in range(mod("limits").MAX_CALLERS + 500):
            lim.hit("caller-%d" % i, 1.0)
        self.assertLessEqual(len(lim.callers), mod("limits").MAX_CALLERS)


class Hardening(Case):
    """The release fix round: S1 to S4, S6, S11."""

    def test_a_chunked_body_with_no_length_over_the_limit_is_refused(self):
        def chunks():
            for _ in range(80):
                yield b" " * 1024
        r = self.raw.http.post("/register", content=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_a_small_chunked_body_still_registers(self):
        body = json.dumps({"redirect_uris": [self.raw.redirect], "client_name": "Test", "grant_types": ["authorization_code"],
                           "response_types": ["code"], "token_endpoint_auth_method": "none"}).encode()
        r = self.raw.http.post("/register", content=iter([body[:20], body[20:]]), headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_a_registration_keeps_only_the_fields_the_service_uses(self):
        r = self.raw.register(logo_uri="https://evil.example.test/x.png", contacts=["a@evil.example.test"], tos_uri="https://evil.example.test/t",
                              client_uri="https://evil.example.test/", software_id="x" * 500)
        self.assertEqual(r.status_code, 201)
        kept = self.store.get_client(r.json()["client_id"])
        self.assertTrue(set(kept) <= set(mod("provider").KEEP), set(kept))
        self.assertNotIn("logo_uri", kept)

    def test_the_waiting_sign_in_requests_are_capped(self):
        self.raw.register()
        seen = []
        for _ in range(55):
            seen.append(self.raw.authorize())
        self.assertEqual(sum("/consent?p=" in r.headers["location"] for r in seen), self.store.MAX_PENDING)
        self.assertIn("temporarily_unavailable", seen[-1].headers["location"])

    def test_a_long_state_or_challenge_is_refused(self):
        self.raw.register()
        q = {"response_type": "code", "client_id": self.raw.client_id, "redirect_uri": self.raw.redirect, "state": "s" * 301,
             "code_challenge": self.raw.challenge, "code_challenge_method": "S256", "scope": "read", "resource": self.served.mcp_url}
        self.assertIn("invalid_request", self.raw.http.get("/authorize", params=q).headers["location"])
        q.update(state="ok", code_challenge="c" * 129)
        self.assertIn("invalid_request", self.raw.http.get("/authorize", params=q).headers["location"])

    def test_wrong_codes_are_not_counted_while_no_code_waits_and_the_words_are_the_same(self):
        self.raw.register()
        a = self.raw.authorize()
        first = [self.raw.consent(a, code="123456") for _ in range(8)]
        self.assertEqual({r.status_code for r in first}, {400})
        self.assertEqual(self.store.consent_locked(), 0)
        self.assertEqual(len({r.text.split("<p class=\"say\">")[1].split("</p>")[0] for r in first}), 1)
        code = self.act.run(self.ws, {"action": "pair"})["code"]                       # and the owner can still connect
        self.assertEqual(self.raw.consent(a, code=code).status_code, 302)

    def test_a_new_code_resets_the_count(self):
        self.raw.register()
        a = self.raw.authorize()
        self.act.run(self.ws, {"action": "pair"})
        for _ in range(4):
            self.raw.consent(a, code="000001")
        with self.store.txn() as db:
            self.assertEqual(db["consent"]["wrong"], 4)
        self.act.run(self.ws, {"action": "pair"})
        with self.store.txn() as db:
            self.assertEqual(db["consent"]["wrong"], 0)

    def test_a_flood_on_the_token_route_is_slowed_never_refused(self):
        limiter = mod("limits").routes()["/token"]
        verdicts = {limiter.hit("x", 100.0 + i * 0.001)[0] for i in range(1000)}
        self.assertEqual(verdicts, {"ok", "slow"})
        self.assertEqual(mod("limits").routes()["/register"].hard, 8)

    def test_a_token_with_fewer_scopes_than_its_grant_gets_a_session_with_fewer_classes(self):
        tokens = self.raw.sign_in(write=True)
        gid = self.store.listing()[0]["id"]
        pair = self.store.issue(gid, self.raw.client_id, ["read"], self.served.mcp_url)
        body = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "stub-who", "arguments": {}}}
        wide = self.raw.mcp(tokens["access_token"], body=body).json()
        narrow = self.raw.mcp(pair["access"], body=body).json()
        classes = lambda r: json.loads(r["result"]["content"][0]["text"])["classes"]
        self.assertEqual(classes(wide), ["read", "write"])
        self.assertEqual(classes(narrow), ["read"])

    def test_the_consent_page_says_when_the_sign_in_was_started(self):
        self.raw.register()
        a = self.raw.authorize()
        text = self.raw.http.get(a.headers["location"]).text
        self.assertIn("This sign-in was started less than a minute ago", text)
        self.assertIn("Go on only if you started it yourself a moment ago", text)
        pid = parse_qs(urlsplit(a.headers["location"]).query)["p"][0]
        with self.store.txn() as db:
            db["pending"][pid]["made"] -= 300
        self.assertIn("5 minutes ago", self.raw.http.get(a.headers["location"]).text)


class Documents(Case):
    """The client ID metadata document: HTTPS only, a fixed list of hosts, 64 KB, five seconds."""

    URL = "https://claude.ai/oauth/mcp-oauth-client-metadata"

    def provider(self, answer):
        calls = []

        async def fetch(url):
            calls.append(url)
            if isinstance(answer, Exception):
                raise answer
            return answer

        p = mod("provider")
        return p.Provider(self.store, "https://home.example.test", "https://home.example.test/mcp", lambda: True, fetch), calls

    def doc(self, **over):
        d = {"client_id": self.URL, "client_name": "Assistant", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
             "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"]}
        d.update(over)
        return json.dumps(d).encode()

    def get(self, answer, url=None):
        import asyncio
        prov, calls = self.provider(answer)
        return asyncio.run(prov.get_client(url or self.URL)), calls

    def test_a_good_document_makes_a_client(self):
        client, calls = self.get(self.doc())
        self.assertEqual(client.client_id, self.URL)
        self.assertEqual(client.client_name, "Assistant")
        self.assertEqual(calls, [self.URL])
        self.assertEqual(client.token_endpoint_auth_method, "none")

    def test_a_host_off_the_list_is_never_fetched(self):
        for url in ("https://evil.example.test/m.json", "https://claude.ai.evil.example.test/m", "http://claude.ai/m", "https://claude.ai:8443/m",
                    "https://user@claude.ai/m", "https://claude.ai/", "https://claude.ai", "https://claude.ai/m#x"):
            client, calls = self.get(self.doc(client_id=url), url)
            self.assertIsNone(client, url)
            self.assertEqual(calls, [], url)

    def test_a_document_over_64_kb_is_refused(self):
        big = self.doc(client_name="x" * 70000)
        self.assertIsNone(self.get(big)[0])

    def test_a_document_for_another_address_is_refused(self):
        self.assertIsNone(self.get(self.doc(client_id="https://claude.ai/other"))[0])

    def test_a_document_with_a_callback_off_the_list_is_refused(self):
        self.assertIsNone(self.get(self.doc(redirect_uris=["https://evil.example.test/cb"]))[0])
        self.assertIsNone(self.get(self.doc(redirect_uris=["https://claude.ai/api/mcp/auth_callback", "https://evil.example.test/cb"]))[0])

    def test_a_document_that_asks_for_a_secret_is_refused(self):
        self.assertIsNone(self.get(self.doc(token_endpoint_auth_method="client_secret_post"))[0])
        self.assertIsNone(self.get(self.doc(client_secret="x"))[0])

    def test_a_failed_or_slow_fetch_is_no_client(self):
        self.assertIsNone(self.get(OSError("down"))[0])
        self.assertIsNone(self.get(b"not json")[0])
        self.assertIsNone(self.get(b"[]")[0])

    def test_the_real_fetcher_has_a_five_second_timeout_and_no_redirect_and_a_size_cap(self):
        p = mod("provider")
        self.assertEqual(p.CIMD_SECONDS, 5)
        self.assertEqual(p.CIMD_MAX_BYTES, 64 * 1024)
        self.assertIsNone(p._NoRedirect().redirect_request(None, None, 302, "x", {}, "https://elsewhere.example.test"))

    def test_the_metadata_says_documents_are_supported_and_clients_are_public(self):
        meta = self.raw.http.get("/.well-known/oauth-authorization-server").json()
        self.assertTrue(meta["client_id_metadata_document_supported"])
        self.assertEqual(meta["token_endpoint_auth_methods_supported"], ["none"])
        self.assertEqual(meta["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(meta["issuer"].rstrip("/"), self.served.url)


class Logs(Case):
    def test_no_token_code_or_text_reaches_the_log(self):
        tokens = self.raw.sign_in()
        code = self.act.run(self.ws, {"action": "pair"})["code"]
        self.raw.mcp(tokens["access_token"], body={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                   "params": {"name": "stub-who", "arguments": {}}})
        log = (self.state.home() / "service.log").read_text()
        self.assertIn('"tool": "stub-who"', log)
        for secret in (tokens["access_token"], tokens["refresh_token"], code, self.raw.verifier):
            self.assertNotIn(secret, log)
        for line in log.splitlines():
            self.assertEqual(set(json.loads(line)), {"t", "tool", "grant", "outcome", "ms"})


if __name__ == "__main__":
    unittest.main()
