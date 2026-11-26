#!/usr/bin/env python3
"""provider.py: the sign-in of remote access (preview): the service is its own authorization server, for one owner.

Built on the MCP SDK's `OAuthAuthorizationServerProvider`. The SDK serves the routes, the metadata, PKCE and the check that a token
was issued for this server. Four pieces are this module's, because the SDK leaves them to the provider:

* the client ID metadata document fetch, in `get_client`: HTTPS only, a fixed list of hosts, at most 64 KB, five seconds;
* the redirect allow-list, with loopback on any port, in `register_client` and `get_client`;
* the list of grants and the owner's revoke (`store.py`, driven from Settings);
* rate limits on the sign-in routes (`service.py`, with `limits.py`).

Plus what the SDK says is the provider's: refresh tokens that rotate, with a refresh token used twice closing the grant; short
access tokens; and tokens bound to this server's address (RFC 8707).

Every token, code and the pairing code is stored as a SHA-256 hash (`store.py`). A client registered by the SDK is made a public client
(no secret), because a secret would have to be stored in clear; the sign-in is protected by PKCE and the owner's pairing code.

Runs in the extra's own runtime (Python 3.12 with the locked packages), never on the Python that macOS ships.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlsplit

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken,
                                      RegistrationError, TokenError, construct_redirect_uri)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken

sys.dont_write_bytecode = True

ALLOWED_REDIRECTS = ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
CIMD_HOSTS = ("claude.ai", "claude.com")             # a client ID that is a web address is fetched only from these
CIMD_MAX_BYTES = 64 * 1024
CIMD_SECONDS = 5
CIMD_KEEP = 3600
SCOPES = ("read", "write")
GRANTS = ["authorization_code", "refresh_token"]
NAME_MAX = 60
KEEP = ("client_id", "client_name", "redirect_uris", "grant_types", "response_types", "scope", "token_endpoint_auth_method",
        "client_id_issued_at")
STATE_MAX = 300
CHALLENGE_MAX = 128


def loopback(uri: str) -> bool:
    """http on 127.0.0.1 or localhost, with no password and no fragment, on any port."""
    try:
        p = urlsplit(uri)
        p.port                                          # noqa: B018 (a bad port raises)
    except ValueError:
        return False
    return p.scheme == "http" and (p.hostname or "") in LOOPBACK_HOSTS and p.username is None and not p.fragment


def redirect_ok(uri: str) -> bool:
    """May the sign-in send a browser to this address? The assistant's two published callbacks, exactly, and loopback."""
    return uri in ALLOWED_REDIRECTS or loopback(uri)


def same_loopback(registered: str, given: str) -> bool:
    """Loopback matches whatever the port, as RFC 8252 says for a command-line client: same host, same path."""
    if not (loopback(registered) and loopback(given)):
        return False
    a, b = urlsplit(registered), urlsplit(given)
    return a.hostname == b.hostname and (a.path or "/") == (b.path or "/") and a.query == b.query


def clean_name(text: Any) -> str:
    """A client name for a page: printable characters only, at most 60, never empty."""
    out = "".join(ch for ch in str(text or "") if ch.isprintable())[:NAME_MAX].strip()
    return out or "An assistant"


class GarrickClient(OAuthClientInformationFull):
    """A registered client whose redirect check is the allow-list's: exact for the published callbacks, any port for loopback."""

    def validate_redirect_uri(self, redirect_uri):                           # type: ignore[override]
        registered = [str(u) for u in (self.redirect_uris or [])]
        if redirect_uri is None:
            if len(registered) == 1 and redirect_ok(registered[0]):
                return self.redirect_uris[0]                                  # type: ignore[index]
            raise InvalidRedirectUriError("redirect_uri must be given.")
        given = str(redirect_uri)
        if redirect_ok(given) and any(given == r or same_loopback(r, given) for r in registered):
            return redirect_uri
        raise InvalidRedirectUriError("That return address is not allowed for this client.")


class GarrickCode(AuthorizationCode):
    grant: str


Fetcher = Callable[[str], Awaitable[bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):                                      # a metadata document that redirects is refused
        return None


async def fetch_document(url: str) -> bytes:
    """The real fetcher: HTTPS, no redirect, five seconds, at most 64 KB. Run in a thread: urllib blocks."""
    def go() -> bytes:
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "garrick-remote"})
        with opener.open(req, timeout=CIMD_SECONDS) as resp:               # noqa: S310 (the host list is checked by the caller)
            body = resp.read(CIMD_MAX_BYTES + 1)
        return body
    return await asyncio.get_running_loop().run_in_executor(None, go)


def document_client(url: str, raw: bytes) -> Optional[GarrickClient]:
    """Check a client ID metadata document and make the client from it, or None. The document must be small, say it is for this
    very address, name only return addresses the allow-list holds, and ask for no secret."""
    if len(raw) > CIMD_MAX_BYTES:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict) or doc.get("client_id") != url:
        return None
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and redirect_ok(u) for u in uris):
        return None
    if doc.get("token_endpoint_auth_method") not in (None, "none") or "client_secret" in doc:
        return None
    grants = doc.get("grant_types")
    if grants is not None and (not isinstance(grants, list) or not set(grants) <= set(GRANTS)):
        return None
    return GarrickClient.model_validate({
        "client_id": url, "client_name": clean_name(doc.get("client_name")), "redirect_uris": uris,
        "token_endpoint_auth_method": "none", "grant_types": GRANTS, "response_types": ["code"], "scope": " ".join(SCOPES)})


class Provider:
    """The provider. `store` is the extra's store module, `resource` and `issuer` the stable address, `active` says whether remote access
    is on right now (a pause or an off makes every token worthless at once), `fetch` gets a client's metadata document."""

    def __init__(self, store, issuer: str, resource: str, active: Callable[[], bool], fetch: Fetcher = fetch_document,
                 clock: Callable[[], float] = time.time):
        self.store, self.issuer, self.resource, self.active, self.fetch, self.clock = store, issuer.rstrip("/"), resource, active, fetch, clock
        self._documents: Dict[str, Any] = {}

    # ---- clients

    async def get_client(self, client_id: str) -> Optional[GarrickClient]:
        if not isinstance(client_id, str) or not client_id or len(client_id) > 2048:
            return None
        if client_id.startswith("https://"):
            return await self._document(client_id)
        info = self.store.get_client(client_id)
        if not info:
            return None
        try:
            client = GarrickClient.model_validate(info)
        except ValueError:
            return None
        return client if all(redirect_ok(str(u)) for u in (client.redirect_uris or [])) else None

    async def _document(self, url: str) -> Optional[GarrickClient]:
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "") not in CIMD_HOSTS or parts.port not in (None, 443) \
                or parts.username is not None or parts.fragment or not parts.path.strip("/"):
            return None
        now = self.clock()
        hit = self._documents.get(url)
        if hit and hit[0] > now:
            return hit[1]
        try:
            raw = await self.fetch(url)
            client = document_client(url, raw)
        except Exception:
            client = None
        self._documents[url] = (now + (CIMD_KEEP if client else 60), client)
        if len(self._documents) > 64:
            self._documents.pop(next(iter(self._documents)))
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not uris or not all(redirect_ok(u) for u in uris):
            raise RegistrationError("invalid_redirect_uri", "That return address is not allowed.")
        if not set(client_info.grant_types) <= set(GRANTS):
            raise RegistrationError("invalid_client_metadata", "That kind of sign-in is not offered.")
        # a public client: no secret is kept, so none is stored in clear
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        client_info.client_name = clean_name(client_info.client_name)
        client_info.scope = " ".join(s for s in (client_info.scope or "read").split() if s in SCOPES) or "read"
        kept = {k: v for k, v in client_info.model_dump(mode="json", exclude_none=True).items() if k in KEEP}      # only what the service uses
        if not self.store.put_client(client_info.client_id, kept, self.clock()):
            raise RegistrationError("invalid_client_metadata", "Too many sign-ins are waiting. Try again later.")

    # ---- sign-in

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") != self.resource.rstrip("/"):
            raise AuthorizeError("invalid_target", "That is not this server's address.")
        if len(params.state or "") > STATE_MAX or len(params.code_challenge or "") > CHALLENGE_MAX:
            raise AuthorizeError("invalid_request", "That request is too long.")
        pid = self.store.put_pending({"client": client.client_id, "name": clean_name(client.client_name),
                                      "challenge": params.code_challenge, "redirect": str(params.redirect_uri),
                                      "explicit": params.redirect_uri_provided_explicitly, "state": params.state or ""},
                                     self.clock())
        if pid is None:
            raise AuthorizeError("temporarily_unavailable", "Too many sign-ins are waiting. Try again later.")
        return "%s/consent?p=%s" % (self.issuer, pid)

    def finish(self, pending_id: str, classes: List[str]) -> Optional[str]:
        """The owner said yes on the consent page: make the grant and the code, and give the address to send the browser to."""
        row = self.store.pop_pending(pending_id, self.clock())
        classes = [c for c in classes if c in SCOPES]
        if not row or not classes:
            return None
        gid = self.store.create_grant(row["client"], row["name"], classes, self.clock())
        code = self.store.put_authcode({"grant": gid, "client": row["client"], "scopes": classes, "challenge": row["challenge"],
                                        "redirect": row["redirect"], "explicit": row["explicit"], "resource": self.resource},
                                       self.clock())
        return construct_redirect_uri(row["redirect"], code=code, state=row["state"] or None)

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> Optional[GarrickCode]:
        row = self.store.load_authcode(authorization_code, self.clock())
        if not row or row["client"] != client.client_id:
            return None
        return GarrickCode(code=authorization_code, scopes=row["scopes"], expires_at=row["expires"], client_id=row["client"],
                           code_challenge=row["challenge"], redirect_uri=row["redirect"],
                           redirect_uri_provided_explicitly=bool(row["explicit"]), resource=row["resource"], grant=row["grant"])

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: GarrickCode) -> OAuthToken:
        row = self.store.spend_authcode(authorization_code.code, self.clock())
        if not row or row["client"] != client.client_id:
            raise TokenError("invalid_grant", "The code was not accepted.")
        pair = self.store.issue(row["grant"], client.client_id, row["scopes"], self.resource, self.clock())
        if pair is None:
            raise TokenError("invalid_grant", "The code was not accepted.")
        return OAuthToken(access_token=pair["access"], expires_in=pair["expires_in"], refresh_token=pair["refresh"],
                          scope=" ".join(row["scopes"]))

    # ---- tokens

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Optional[RefreshToken]:
        row = self.store.lookup_refresh(refresh_token, self.clock())
        if not row or row["client"] != client.client_id or not self.active():
            return None
        return RefreshToken(token=refresh_token, client_id=row["client"], scopes=row["scopes"], expires_at=int(row["expires"]),
                            resource=row["resource"], subject=row["grant"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: List[str]) -> OAuthToken:
        if not self.active():
            raise TokenError("invalid_grant", "The token was not accepted.")
        pair = self.store.rotate(refresh_token.token, scopes, self.clock())
        if pair is None:
            raise TokenError("invalid_grant", "The token was not accepted.")
        granted = [s for s in scopes if s in refresh_token.scopes] or refresh_token.scopes
        return OAuthToken(access_token=pair["access"], expires_in=pair["expires_in"], refresh_token=pair["refresh"], scope=" ".join(granted))

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """The one door every call passes. No token the store does not know, none past its time, none of a revoked grant, none issued for
        another resource, and none at all while remote access is off or paused."""
        if not self.active():
            return None
        row = self.store.lookup_access(token, self.clock())
        if not row or str(row["resource"]).rstrip("/") != self.resource.rstrip("/"):
            return None
        return AccessToken(token=token, client_id=row["client"], scopes=row["scopes"], expires_at=int(row["expires"]),
                           resource=row["resource"], subject=row["grant"], claims={"iss": self.issuer})

    async def revoke_token(self, token) -> None:
        self.store.drop_token(token.token)
