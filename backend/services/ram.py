"""
SAS Retrieval Agent Manager (RAM) client.

Wraps the RAM REST API (OpenAPI v1) and handles SAS Viya authentication.
The browser never talks to RAM directly — this backend proxies every call,
which keeps the bearer token server-side and avoids CORS issues.

Auth options (checked in order):
    RAM_TOKEN            — static bearer token (simplest; expires per policy)
    SAS_CLIENT_ID/SECRET — OAuth client_credentials grant
                           (add SAS_USERNAME/SAS_PASSWORD for the password grant)
    device code flow     — default for standalone RAM (Keycloak): no configuration
                           needed; the UI's "Sign in" button drives the flow against
                           the pre-configured public client (RAM_CLIENT_ID, default
                           "sas-ram-api") with PKCE, and the backend keeps the
                           session alive with the refresh token.
    authorization code   — full SAS Viya (SASLogon), detected automatically: the user
                           logs in on the SAS page and pastes the code it shows
                           (SAS_AUTH_CLIENT_ID, default "sas.cli").

Staying signed in (interactive flows): each browser gets its own RAM identity
(an HttpOnly cookie the router maps to a token entry), the entries are written
to RAM_SESSION_FILE so a backend restart does not sign anyone out, a keep-alive
loop refreshes every session before its access token expires so an idle
conversation does not either, and the browser keeps a copy of its own refresh
token (localStorage) to hand back after a redeploy on a fresh container
(RAM_BROWSER_RESTORE=false disables that last part).

Other env vars:
    RAM_API_URL     — https://host/SASRetrievalAgentManager/api/v1. The address RAM is
                      opened at in a browser (…/SASRetrievalAgentManager) works too:
                      /api/v1 is added. Setting it is what connects the app: it wins
                      over RAM_MOCK.
    SAS_LOGON_URL   — override the OAuth token endpoint (default derived from RAM_API_URL)
    RAM_CLIENT_ID   — public client for the device flow (default "sas-ram-api")
    RAM_REALM       — Keycloak realm for standalone RAM (default "sas-iot")
    RAM_AUTH_FLOW   — force "device" (Keycloak) or "code" (Viya SASLogon paste-the-code)
    RAM_VERIFY_SSL  — "false" to skip TLS verification (self-signed certs)
    RAM_MOCK        — "true" to run against an in-memory mock (UI demo without RAM).
                      Only applies while no RAM address is set.
    RAM_HIDE_HISTORY — "true" to hide RAM's session history (only needed when several
                       people share one RAM login)
    RAM_SESSION_FILE — where signed-in sessions are persisted (default data/runtime/ram_sessions.json;
                       point it at a mounted volume on Railway to survive redeploys)
    RAM_BROWSER_RESTORE — "false" to stop handing the browser a copy of its own session
    RAM_KEEPALIVE_SECONDS — how often the keep-alive loop looks for tokens to refresh (default 60)
    RAM_QUERY_TIMEOUT / RAM_QUERY_POLL_INTERVAL — async query wait bounds (seconds)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger(__name__)

RAM_PATH = "/SASRetrievalAgentManager"


# The Agentic-Bootcamp app keeps one RAM per "environment" (ENV1_…, ENV2_…). This
# app talks to one RAM, so it also understands the first environment's names:
# that app's variables can be copied to this one as they are.
_BOOTCAMP_NAMES = {"RAM_REALM": "ENV1_RAM_REALM", "RAM_CLIENT_ID": "ENV1_RAM_CLIENT_ID"}


def _cfg(name: str, default: str = "") -> str:
    """An environment setting, stripped; `default` when unset or blank (a
    variable left empty in a hosting dashboard counts as unset)."""
    value = (os.getenv(name) or "").strip()
    if not value and name in _BOOTCAMP_NAMES:
        value = (os.getenv(_BOOTCAMP_NAMES[name]) or "").strip()
    return value or default


def normalize_api_url(raw: str) -> str:
    """The RAM API base from whatever address was configured.

    The API lives at https://host/SASRetrievalAgentManager/api/v1. The common
    slip is pasting the address RAM is opened at in a browser instead, which
    makes every call a 404, so accept that too: a bare host, or anything under
    /SASRetrievalAgentManager that is not already an /api/ path."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    if "/api/" in url + "/":
        return url
    if RAM_PATH in url:
        return url.split(RAM_PATH)[0] + RAM_PATH + "/api/v1"
    if urlsplit(url).path in ("", "/"):
        return url + RAM_PATH + "/api/v1"
    return url


# Where the RAM address is read from, first one set wins. RAM_API_URL is this
# app's name for it; the others are the Agentic-Bootcamp app's (see _BOOTCAMP_NAMES).
ADDRESS_VARIABLES = ("RAM_API_URL", "ENV1_RAM_API_URL", "ENV1_RAM_URL", "RAM_URL")


def _configured_address() -> tuple[str, str]:
    """(address, the variable it came from). A value still holding the
    placeholder from .env.example ("your-ram-host", "<host>") is not an address."""
    for name in ADDRESS_VARIABLES:
        value = _cfg(name)
        if value and "your-ram-host" not in value and "<" not in value:
            return value, name
    return "", ""


_address, ADDRESS_SOURCE = _configured_address()
RAM_API_URL = normalize_api_url(_address)


def _api_url() -> str:
    return RAM_API_URL


VERIFY_SSL = _cfg("RAM_VERIFY_SSL", "true").lower() != "false"
# The mock is a demo for when there is no RAM to talk to. A RAM address always
# wins over it: with both set, a page that quietly shows made-up agents instead
# of the RAM that was configured is the worse surprise.
MOCK_REQUESTED = _cfg("RAM_MOCK").lower() == "true"
MOCK = MOCK_REQUESTED and not RAM_API_URL

TIMEOUT = httpx.Timeout(10.0, read=180.0)

# Queries are submitted asynchronously (synchronous=false) and polled, so no
# single HTTP request to RAM outlives its gateway's timeout. These bound the
# overall wait for an answer and the poll cadence.
QUERY_TIMEOUT = float(_cfg("RAM_QUERY_TIMEOUT", "600"))
QUERY_POLL_INTERVAL = float(_cfg("RAM_QUERY_POLL_INTERVAL", "2"))


class RamError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


# ─── Token management ────────────────────────────────────────────────
# One RAM identity per browser. The router puts the browser's session id (an
# HttpOnly cookie) into _current_sid before every call and the tokens live
# under that id, so two people signed in as different users never overwrite
# each other. The static (RAM_TOKEN) and service-account (SAS_CLIENT_ID)
# modes are one shared identity and use the "_shared" entry.
#
# Entries that hold a refresh token are persisted to RAM_SESSION_FILE (mode
# 0600) so a restart does not sign anyone out, and keepalive_loop() refreshes
# them before they expire so an idle conversation does not either.
_current_sid: ContextVar[str | None] = ContextVar("ram_sid", default=None)
_sessions: dict[str, dict[str, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_SHARED = "_shared"
SESSION_FILE = _cfg("RAM_SESSION_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "runtime" / "ram_sessions.json")
_PERSISTED_KEYS = ("token", "expires_at", "refresh_token", "token_url", "client_id", "auth_style", "stamp")
# What the browser's own copy carries: enough to refresh, never the access token.
_EXPORTED_KEYS = ("refresh_token", "token_url", "client_id", "auth_style")
# Refresh when this little lifetime is left: comfortably more than one keep-alive
# tick, so a token never expires between two ticks.
KEEPALIVE_INTERVAL = float(_cfg("RAM_KEEPALIVE_SECONDS", "60"))
KEEPALIVE_MARGIN = max(120.0, 2 * KEEPALIVE_INTERVAL)
_loaded = False


def _static_token() -> str:
    """RAM_TOKEN, tolerating a pasted "Bearer " prefix."""
    token = _cfg("RAM_TOKEN")
    return token[7:].strip() if token.lower().startswith("bearer ") else token


def set_session_id(sid: str | None) -> None:
    """Bind the current request to a browser session (called by the router)."""
    _current_sid.set(sid)


def _sid() -> str:
    if _static_token() or _cfg("SAS_CLIENT_ID"):
        return _SHARED
    return _current_sid.get() or _SHARED


def _new_entry() -> dict[str, Any]:
    return {"token": None, "expires_at": 0.0, "refresh_token": None, "device": {}, "stamp": 0}


def _peek(sid: str | None = None) -> dict[str, Any]:
    """The session's entry without creating one: a status check from a browser
    that never signs in (or from a crawler) must not leave an entry behind."""
    _load_sessions()
    return _sessions.get(sid or _sid()) or _new_entry()


def _entry(sid: str | None = None) -> dict[str, Any]:
    _load_sessions()
    sid = sid or _sid()
    e = _sessions.get(sid)
    if e is None:
        e = _sessions[sid] = _new_entry()
    return e


def _lock(sid: str) -> asyncio.Lock:
    # Serializes token refreshes per session. While a query runs the frontend
    # polls the result plus the trace endpoints every couple of seconds, so
    # several RAM calls are always in flight. When the access token expires
    # mid-query they would otherwise all refresh at once — and Keycloak rotates
    # the refresh token on every use and revokes the whole family if a used
    # token is presented again, so a stampede signs the user out (the "logged
    # out on a long question" bug). With the lock one coroutine refreshes and
    # the rest reuse the token it stored.
    lock = _locks.get(sid)
    if lock is None:
        lock = _locks[sid] = asyncio.Lock()
    return lock


def _load_sessions() -> None:
    global _loaded
    if _loaded or MOCK:
        return
    _loaded = True
    try:
        data = json.loads(Path(SESSION_FILE).read_text())
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for sid, e in data.items():
        if isinstance(e, dict) and e.get("refresh_token") and sid not in _sessions:
            _sessions[sid] = {**_new_entry(), **{k: e.get(k) for k in _PERSISTED_KEYS if k in e}}


def _save_sessions() -> None:
    if MOCK:
        return
    data = {sid: {k: e.get(k) for k in _PERSISTED_KEYS}
            for sid, e in _sessions.items() if e.get("refresh_token")}
    try:
        path = Path(SESSION_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass  # read-only filesystem: sessions simply live in memory


def _browser_restore() -> bool:
    return _cfg("RAM_BROWSER_RESTORE", "true").lower() != "false"


def export_session() -> dict | None:
    """The current browser's session, for it to keep and hand back after a
    redeploy (see restore_session). None when disabled or not signed in.

    `stamp` changes every time the identity provider issues a new refresh
    token. Every API response carries the current one (X-Session-Stamp) and
    the browser fetches a fresh copy when it differs from the one it holds,
    so its copy is not left with a refresh token the provider has since
    rotated away."""
    if not _browser_restore():
        return None
    e = _peek()
    if not e.get("refresh_token"):
        return None
    return {**{k: e.get(k) for k in _EXPORTED_KEYS}, "stamp": e.get("stamp") or 0}


def session_stamp(sid: str | None = None) -> int | None:
    """The stamp of a browser's interactive session, or None when there is
    nothing for the browser to keep a copy of (not signed in, a configured
    identity, the mock, or restore switched off)."""
    if MOCK or not _browser_restore():
        return None
    sid = sid or _sid()
    if sid == _SHARED or _static_token() or _cfg("SAS_CLIENT_ID"):
        return None
    e = _peek(sid)
    return (e.get("stamp") or 0) if e.get("refresh_token") else None


async def restore_session(data: Any) -> dict:
    """Install a session the browser saved earlier, validating it with the
    identity provider (one refresh). Only sessions minted for this RAM
    environment's token endpoints are accepted."""
    if not _browser_restore():
        raise RamError(403, "Session restore is disabled on this server.")
    if not isinstance(data, dict) or not data.get("refresh_token") or not data.get("token_url"):
        raise RamError(400, "Nothing to restore.")
    allowed = {f"{_oidc_base()}/token", f"{_viya_logon_base()}/oauth/token", _logon_url()}
    if data["token_url"] not in allowed:
        raise RamError(400, "The saved session belongs to a different RAM environment.")
    sid = _sid()
    async with _lock(sid):
        e = _entry(sid)
        if e.get("refresh_token") and e["token"] and time.time() < e["expires_at"]:
            return {"ok": True, "session": export_session()}  # already signed in here
        e.update({k: data.get(k) for k in _EXPORTED_KEYS})
        e["token"], e["expires_at"] = None, 0.0  # force the validating refresh
        token = await _refresh_token_grant(e)
    if not token:
        raise RamError(401, "The saved session has expired — sign in again.")
    return {"ok": True, "session": export_session()}


async def sign_out() -> dict:
    """End the current browser's RAM session: revoke its refresh token at the
    identity provider where that is possible (Keycloak's logout endpoint takes
    the refresh token; SASLogon has no equivalent for a public client, so
    there the tokens are simply forgotten and left to expire), then drop the
    entry from memory and from the session file."""
    sid = _sid()
    if sid == _SHARED:
        raise RamError(400, "This deployment signs in with a configured token, so there is nothing to sign out of.")
    async with _lock(sid):
        e = _sessions.pop(sid, None) or {}
        _locks.pop(sid, None)
        _save_sessions()
    refresh, token_url = e.get("refresh_token"), e.get("token_url") or ""
    revoked = False
    if refresh and "/protocol/openid-connect/" in token_url and e.get("auth_style") != "basic":
        try:
            async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
                r = await client.post(token_url.rsplit("/token", 1)[0] + "/logout", data={
                    "client_id": e.get("client_id") or _cfg("RAM_CLIENT_ID", "sas-ram-api"),
                    "refresh_token": refresh,
                })
            revoked = r.status_code in (200, 204)
        except httpx.HTTPError:
            revoked = False  # best effort: the session is gone locally either way
    return {"ok": True, "revoked": revoked}


async def _keepalive_once() -> None:
    _load_sessions()
    for sid, e in list(_sessions.items()):
        if not e.get("refresh_token"):
            device = e.get("device") or {}
            if device and time.time() > device.get("expires_at", 0):
                device = e["device"] = {}  # a sign-in nobody finished
            if not e.get("token") and not device:
                _sessions.pop(sid, None)  # signed out and idle: forget it
                _locks.pop(sid, None)
            continue
        if e["expires_at"] - time.time() < KEEPALIVE_MARGIN:
            async with _lock(sid):
                if e["expires_at"] - time.time() < KEEPALIVE_MARGIN:
                    await _refresh_token_grant(e)


async def keepalive_loop() -> None:
    """Refresh every signed-in session before its access token expires, which
    also keeps the identity provider's idle timer from signing it out.
    Started by the app's lifespan; harmless when nothing is signed in."""
    if MOCK or _static_token() or not RAM_API_URL:
        return
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL)
        try:
            await _keepalive_once()
        except Exception:
            logger.debug("keep-alive tick failed; retrying on the next one", exc_info=True)


def _oidc_base() -> str:
    """Keycloak OpenID Connect base for standalone RAM, e.g.
    https://host/SASRetrievalAgentManager/auth/realms/sas-iot/protocol/openid-connect"""
    explicit = _cfg("SAS_LOGON_URL")
    if explicit and "/protocol/openid-connect" in explicit:
        return explicit.split("/protocol/openid-connect")[0] + "/protocol/openid-connect"
    base = _api_url().split("/api/")[0]  # strip /api/v1
    realm = _cfg("RAM_REALM", "sas-iot")
    return f"{base}/auth/realms/{realm}/protocol/openid-connect"


def _logon_url() -> str:
    explicit = _cfg("SAS_LOGON_URL")
    if explicit:
        return explicit
    # Derive https://host/SASLogon/oauth/token from the RAM URL (full Viya);
    # standalone RAM deployments go through _oidc_base() instead.
    base = _api_url().split("/SASRetrievalAgentManager")[0]
    return f"{base}/SASLogon/oauth/token"


def _store_tokens(body: dict, *, token_url: str | None = None,
                  client_id: str | None = None, auth_style: str = "body",
                  entry: dict | None = None) -> None:
    e = entry if entry is not None else _entry()
    e["token"] = body["access_token"]
    # Refresh shortly before actual expiry
    e["expires_at"] = time.time() + int(body.get("expires_in", 300)) - 30
    if body.get("refresh_token") and body["refresh_token"] != e.get("refresh_token"):
        e["refresh_token"] = body["refresh_token"]
        e["stamp"] = int(time.time() * 1000)
    if token_url:
        e["token_url"] = token_url
        e["client_id"] = client_id
        e["auth_style"] = auth_style  # "basic" (UAA/SASLogon) or "body" (Keycloak public)
    _save_sessions()


# ─── Sign-in flow detection ──────────────────────────────────────────
# Standalone RAM ships Keycloak (device code flow); full SAS Viya uses
# SASLogon (authorization code flow with the sas.cli public client).
_flow_cache: dict[str, str] = {}  # RAM api url -> "device" | "code"


def _viya_logon_base() -> str:
    explicit = _cfg("SAS_LOGON_URL")
    if explicit:
        return explicit.split("/oauth/")[0]
    return _api_url().split("/SASRetrievalAgentManager")[0] + "/SASLogon"


async def detect_signin_flow() -> str:
    """Return "device" (Keycloak) or "code" (Viya SASLogon paste-the-code)."""
    env = _cfg("RAM_AUTH_FLOW").lower()
    if env in ("device", "code"):
        return env
    api = _api_url()
    if not api:
        return "device"
    if _flow_cache.get(api):
        return _flow_cache[api]
    realm = _cfg("RAM_REALM", "sas-iot")
    base = api.split("/api/")[0]
    try:
        async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=httpx.Timeout(8.0)) as client:
            r = await client.get(f"{base}/auth/realms/{realm}/.well-known/openid-configuration")
        _flow_cache[api] = "device" if r.status_code == 200 else "code"
    except Exception:
        return "device"  # don't cache on network errors — retry next time
    return _flow_cache[api]


# ─── Viya SASLogon authorization code flow (sas.cli public client) ───
# Visiting /SASLogon/oauth/authorize?client_id=sas.cli&response_type=code
# displays an authorization code after login (SSO included); the user
# pastes it into the UI and we exchange it for tokens here.
def viya_authorize_url() -> str:
    client_id = _cfg("SAS_AUTH_CLIENT_ID", "sas.cli")
    return f"{_viya_logon_base()}/oauth/authorize?client_id={client_id}&response_type=code"


async def viya_code_exchange(code: str) -> dict:
    client_id = _cfg("SAS_AUTH_CLIENT_ID", "sas.cli")
    client_secret = _cfg("SAS_AUTH_CLIENT_SECRET")
    token_url = f"{_viya_logon_base()}/oauth/token"
    async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
        r = await client.post(token_url,
                              data={"grant_type": "authorization_code", "code": code.strip()},
                              auth=(client_id, client_secret))
    if r.status_code != 200:
        raise RamError(r.status_code, f"Sign-in failed — SASLogon said: {r.text[:300]}")
    _store_tokens(r.json(), token_url=token_url, client_id=client_id, auth_style="basic")
    return {"ok": True}


# ─── Device code flow (standalone RAM / Keycloak public client) ──────
async def device_start() -> dict:
    """Begin a device authorization (PKCE). Returns the code/URL the user needs."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    client_id = _cfg("RAM_CLIENT_ID", "sas-ram-api")
    async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
        r = await client.post(f"{_oidc_base()}/auth/device", data={
            "client_id": client_id,
            "scope": "openid",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
    if r.status_code != 200:
        raise RamError(r.status_code, f"Device authorization failed: {r.text[:300]}")
    body = r.json()
    _entry()["device"] = {"verifier": verifier, "device_code": body["device_code"],
                          "expires_at": time.time() + int(body.get("expires_in") or 600)}
    return {
        "userCode": body.get("user_code"),
        "verificationUri": body.get("verification_uri"),
        "verificationUriComplete": body.get("verification_uri_complete"),
        "expiresIn": body.get("expires_in"),
        "interval": body.get("interval", 5),
    }


async def device_poll() -> dict:
    """Poll Keycloak until the user approves the device authorization."""
    device = _entry().get("device") or {}
    if not device.get("device_code"):
        raise RamError(400, "No device authorization in progress — start a sign-in first.")
    client_id = _cfg("RAM_CLIENT_ID", "sas-ram-api")
    async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
        r = await client.post(f"{_oidc_base()}/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device["device_code"],
            "code_verifier": device["verifier"],
            "client_id": client_id,
        })
    try:
        body = r.json()
    except Exception:
        raise RamError(r.status_code, r.text[:300])
    if r.status_code != 200:
        error = body.get("error", "")
        if error in ("authorization_pending", "slow_down"):
            return {"pending": True, "slowDown": error == "slow_down"}
        _entry()["device"] = {}
        raise RamError(r.status_code, body.get("error_description") or error or r.text[:300])
    _store_tokens(body, token_url=f"{_oidc_base()}/token", client_id=client_id, auth_style="body")
    _entry()["device"] = {}
    return {"ok": True}


async def _refresh_token_grant(entry: dict | None = None) -> str | None:
    """Renew the access token with the stored refresh token (any sign-in flow).

    The caller holds the session's lock, so this is the only refresh in flight
    for it — the stored refresh token is therefore used exactly once, which is
    what Keycloak's rotation/reuse-detection requires."""
    e = entry if entry is not None else _entry()
    refresh = e.get("refresh_token")
    token_url = e.get("token_url")
    if not refresh or not token_url:
        return None
    client_id = e.get("client_id") or _cfg("RAM_CLIENT_ID", "sas-ram-api")
    data = {"grant_type": "refresh_token", "refresh_token": refresh}
    auth = None
    if e.get("auth_style") == "basic":
        auth = (client_id, _cfg("SAS_AUTH_CLIENT_SECRET"))
    else:
        data["client_id"] = client_id
    try:
        async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
            r = await client.post(token_url, data=data, auth=auth)
    except httpx.HTTPError:
        # Network blip — keep the refresh token so the next call can retry
        # instead of forcing the user to sign in again.
        return None
    if r.status_code == 200:
        _store_tokens(r.json(), entry=e)
        return e["token"]
    if r.status_code in (400, 401):
        # invalid_grant: the refresh token is genuinely expired or revoked —
        # only now drop it so the UI prompts for a fresh sign-in.
        e["refresh_token"] = None
        _save_sessions()
    # 5xx / other transient errors: leave the refresh token in place to retry.
    return None


async def _fetch_oauth_token() -> str:
    client_id = _cfg("SAS_CLIENT_ID")
    client_secret = _cfg("SAS_CLIENT_SECRET")
    username = _cfg("SAS_USERNAME")
    password = os.getenv("SAS_PASSWORD") or ""  # not stripped: a password may end in a space
    if not client_id:
        raise RamError(500, "No RAM_TOKEN and no SAS_CLIENT_ID configured — cannot authenticate to SAS Viya.")

    if username and password:
        data = {"grant_type": "password", "username": username, "password": password}
    else:
        data = {"grant_type": "client_credentials"}

    # SASLogon (UAA) wants client auth via HTTP Basic (empty secret is fine for
    # public clients like sas.cli); Keycloak public clients want client_id in
    # the form body. Try Basic first, fall back to the body style.
    async with httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT) as client:
        r = await client.post(_logon_url(), data=data, auth=(client_id, client_secret))
        if r.status_code in (400, 401) and not client_secret:
            r = await client.post(_logon_url(), data={**data, "client_id": client_id})
    if r.status_code != 200:
        raise RamError(r.status_code, f"Token request failed: {r.text[:300]}")
    body = r.json()
    e = _entry(_SHARED)
    e["token"] = body["access_token"]
    # Refresh a minute before actual expiry
    e["expires_at"] = time.time() + int(body.get("expires_in", 3600)) - 60
    return e["token"]


async def _get_token(invalid_token: str | None = None) -> str:
    """Return a usable bearer token, refreshing if needed.

    Pass the token that just drew a 401 as `invalid_token`: a coroutine whose
    request was rejected then either reuses a token another coroutine already
    refreshed, or — if it's the first to notice — does the single refresh
    itself. The refresh path is serialized by the session's lock so concurrent
    callers never stampede the (single-use, rotating) refresh token."""
    static = _static_token()
    if static:
        return static
    sid = _sid()
    e = _entry(sid)
    # Fast path: a valid, not-just-rejected cached token. No lock, no refresh —
    # so normal operation pays nothing for the serialization below.
    cached = e["token"]
    if cached and cached != invalid_token and time.time() < e["expires_at"]:
        return cached
    async with _lock(sid):
        # Re-check under the lock: another coroutine may have refreshed while we
        # waited, in which case we just reuse its freshly stored token.
        cached = e["token"]
        if cached and cached != invalid_token and time.time() < e["expires_at"]:
            return cached
        refreshed = await _refresh_token_grant(e)
        if refreshed:
            return refreshed
        if _cfg("SAS_CLIENT_ID"):
            return await _fetch_oauth_token()
        raise RamError(401, "Not signed in — click “Sign in” in the header to authenticate with RAM.")


# ─── HTTP helper ─────────────────────────────────────────────────────
# One pooled client for every proxied RAM call. Fifty browsers polling a running
# query is a few hundred requests a minute; a fresh TLS connection for each was
# the single biggest cost under that load. Created lazily on the running loop.
_http: httpx.AsyncClient | None = None
_HTTP_LIMITS = httpx.Limits(max_connections=200, max_keepalive_connections=50)


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(verify=VERIFY_SSL, timeout=TIMEOUT, limits=_HTTP_LIMITS)
    return _http


async def _request(method: str, path: str, *, params: dict | None = None, json: dict | None = None,
                   with_response: bool = False) -> Any:
    if MOCK:
        data = await _mock_request(method, path, params=params, json=json)
        return (data, None) if with_response else data
    api = _api_url()
    if not api:
        raise RamError(500, "No RAM address is configured. Set RAM_API_URL (in backend/.env for a local "
                            "run, in the Variables tab on Railway) and restart.")

    token = await _get_token()
    url = f"{api}{path}"
    # Retry transient connection drops (e.g. RAM or its gateway closing a
    # connection — "Server disconnected without sending a response", a
    # RemoteProtocolError — which happens under intermittent/concurrent load).
    # Without this a single blip surfaces to the user as a failed turn; a fresh
    # connection on retry almost always succeeds. Backs off briefly between
    # attempts. The 401 access-token retry is nested inside each attempt.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            client = _client()
            r = await client.request(method, url, params=params, json=json,
                                     headers={"Authorization": f"Bearer {token}"})
            # One retry on 401 in case the access token just expired. Hand the
            # rejected token to _get_token so the refresh stays single-flight:
            # if a concurrent call already refreshed we reuse its token, and we
            # never refresh a token that's already been rotated (which Keycloak
            # would treat as reuse and revoke the whole session).
            if r.status_code == 401 and not _static_token():
                token = await _get_token(invalid_token=token)
                r = await client.request(method, url, params=params, json=json,
                                         headers={"Authorization": f"Bearer {token}"})
            break  # got an HTTP response (any status) — stop retrying
        except httpx.TransportError as e:
            last_exc = e
            if attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
    if r.status_code >= 400:
        try:
            message = r.json().get("message", r.text[:300])
        except Exception:
            message = r.text[:300]
        raise RamError(r.status_code, message)
    data = r.json() if r.content else None
    return (data, r) if with_response else data


# ─── Public API ──────────────────────────────────────────────────────
async def list_agents() -> list[dict]:
    body = await _request("GET", "/agents", params={"limit": 100})
    return body.get("items") or []


async def list_collections() -> list[dict]:
    body = await _request("GET", "/collections", params={"limit": 100})
    return body.get("items") or []


async def list_sessions() -> list[dict]:
    # In a shared-identity deployment (one RAM token/login for several users —
    # e.g. a bootcamp) every user queries RAM as the same identity, so RAM's
    # session history is shared: each person would see everyone else's
    # conversations in "Recent conversations". Set RAM_HIDE_HISTORY=true to
    # suppress the shared list — each browser then keeps only its own live
    # session. (True per-user history requires per-user RAM logins.)
    if _cfg("RAM_HIDE_HISTORY").lower() == "true":
        return []
    body = await _request("GET", "/querySessions", params={"limit": 100, "sortBy": "updateTimestamp:descending"})
    sessions = body.get("items") or []
    # Annotate each session with the agent/collections its queries targeted so
    # the UI can scope "Recent conversations" to the selected target. Sessions
    # don't carry this themselves, so derive it from the query records.
    targets: dict[str, dict] = {}
    try:
        # GET /query caps limit at 100 — page through (bounded) to cover history
        for start in range(0, 1000, 100):
            qbody = await _request("GET", "/query", params={"limit": 100, "start": start})
            items = qbody.get("items") or []
            for q in items:
                sid = q.get("querySessionId")
                if not sid or sid in targets:
                    continue
                targets[sid] = {"target": q.get("target"), **_target_ids(q)}
            if len(items) < 100:
                break
    except RamError:
        pass  # best-effort: an unannotated history is better than no history
    return [{**s, **targets.get(s.get("id"), {})} for s in sessions]


def _target_ids(q: dict) -> dict:
    """targetId comes back as e.g. {"agentId": …} or {"configurationIds": […]},
    with snake_case variants in some responses."""
    tid = q.get("targetId") or {}
    return {
        "agentId": tid.get("agentId") or tid.get("agent_id"),
        "collectionIds": (tid.get("configurationIds") or tid.get("configuration_ids")
                          or tid.get("collectionIds") or tid.get("collection_ids") or []),
    }


async def delete_session(session_id: str) -> dict:
    """Delete a query session server-side.

    The v1 OpenAPI spec has no DELETE /querySessions/{id} — /querySessions is
    GET-only — so against current RAM builds this reports "not supported" and
    the frontend falls back to hiding the session locally. The attempt is kept
    (rather than hardcoding failure) so deletion starts working the moment a
    RAM version ships the endpoint, and the mock supports it for UI demos.

    A 404 from the DELETE is ambiguous: either the session is already gone
    (fine — deletes are idempotent) or this RAM build doesn't expose the
    endpoint at all. Disambiguate by checking whether the session still
    exists, so an unsupported endpoint surfaces as a clear error instead of
    a silent no-op.
    """
    try:
        await _request("DELETE", f"/querySessions/{quote(session_id, safe='')}")
        return {"ok": True}
    except RamError as e:
        if e.status == 405 or e.status == 501:
            raise RamError(e.status, "This RAM deployment does not support deleting query sessions.")
        if e.status != 404:
            raise
    body = await _request("GET", "/querySessions",
                          params={"filter": f"eq(id,'{session_id}')", "limit": 1})
    if body.get("items"):
        raise RamError(501, "This RAM deployment does not support deleting query sessions "
                            "(DELETE /querySessions/{id} returned 404 but the session still exists).")
    return {"ok": True}


async def list_session_queries(session_id: str, *, raw: bool = False) -> list[dict] | dict:
    body = await _request("GET", "/query", params={"filter": f"eq(querySessionId,'{session_id}')", "limit": 100})
    items = body.get("items") or []
    if raw:
        # Diagnostics: what a query record looks like on this RAM build, so an
        # ordering problem can be read off one paste instead of guessed at.
        first = items[0] if items else {}
        return {"count": len(items), "keys": sorted(first.keys()),
                "timestamp_by_item": [_query_timestamp(q) for q in items],
                "order_as_returned": [str(q.get("content"))[:40] for q in items],
                "sample": {k: (v if k != "response" else "…") for k, v in first.items()}}
    # Order chronologically — RAM doesn't guarantee an order on this endpoint,
    # and an unordered list reconstructs the conversation with turns scrambled.
    # ISO-8601 timestamps sort lexically; undated items keep their place (stable sort).
    if any(_query_timestamp(q) for q in items):
        items.sort(key=_query_timestamp)
    else:
        # No timestamp on the records at all. RAM lists newest first (its
        # sessions endpoint defaults to descending too, and a reloaded chat
        # came back exactly reversed), so flip it to read top to bottom.
        logger.warning("RAM query records carry no timestamp (keys: %s); assuming newest-first",
                       sorted(items[0].keys()) if items else [])
        items.reverse()
    # A conversation turn is a top-level *user* query. Querying an agent also
    # records the agent's own internal sub-queries (origin "agent", each with a
    # parentQueryId) under the same session id — rendering those as chat bubbles
    # is what made reloaded conversations look garbled. Keep only the user turns.
    turns = [q for q in items
             if (q.get("origin") or "user") == "user" and not q.get("parentQueryId")]
    normalized = [_normalize_query(q) for q in turns]
    # Re-attach each agent turn's tool calls (with their outputs) so an inline
    # chart renders on reload exactly like a live answer. RAM's persisted
    # response.toolCalls omits the tool *outputs* where the render_chart
    # spec lives, so without this the chart would be missing from history.
    await _attach_tool_outputs([n for n in normalized
                                if n.get("queryId") and n.get("target") == "agent"])
    return normalized


async def _attach_tool_outputs(turns: list[dict], *, concurrency: int = 8) -> None:
    """Fetch /toolCalls for each turn and stash them under `trace` (bounded
    concurrency so a long history doesn't stampede RAM). Best-effort: a turn
    whose trace can't be fetched simply renders without its chart."""
    if not turns:
        return
    sem = asyncio.Semaphore(concurrency)

    async def one(turn: dict) -> None:
        async with sem:
            try:
                body = await _request("GET", "/toolCalls",
                                      params={"filter": f"eq(parentQueryId,'{turn['queryId']}')", "limit": 100})
            except Exception:
                return
            items = body.get("items") or []
            if items:
                turn["trace"] = {"toolCalls": items}

    await asyncio.gather(*(one(t) for t in turns), return_exceptions=True)


async def submit_query(content: str, *, agent_id: str | None = None,
                       collection_ids: list[str] | None = None,
                       session_id: str | None = None) -> dict:
    payload: dict[str, Any] = {"content": content}
    if agent_id:
        payload["agentId"] = agent_id
    elif collection_ids:
        payload["collectionIds"] = collection_ids
    else:
        raise RamError(400, "Either an agent or at least one collection must be selected.")
    if session_id:
        payload["querySessionId"] = session_id

    # Submit asynchronously: a synchronous POST /query holds one HTTP request
    # open for the whole agent run, which gateways in front of RAM kill with
    # "504 upstream request timeout" on slow queries. The frontend polls
    # /api/query/{id} for the result and /api/query/{id}/trace for live
    # tool/LLM/retrieval activity while it runs.
    body, resp = await _request("POST", "/query", params={"synchronous": "false", "persistent": "true"},
                                json=payload, with_response=True)
    out = {
        "queryId": _extract_query_id(body, resp),
        "querySessionId": (body or {}).get("querySessionId") or session_id,
        "pollInterval": QUERY_POLL_INTERVAL,
        "timeout": QUERY_TIMEOUT,
    }
    if _query_finished(body):  # the mock (and a sync-answering RAM) returns the result inline
        out["result"] = _normalize_query(body)
    elif not out["queryId"]:
        raise RamError(502, "RAM accepted the query but returned no query id to poll. "
                            f"Submit response: {str(body)[:200]!r}")
    return out


async def query_status(query_id: str) -> dict:
    q = await _fetch_query(query_id)
    if not _query_finished(q):
        return {"done": False}
    return {"done": True, "result": _normalize_query(q)}


async def query_trace(query_id: str) -> dict:
    """The tool, LLM, and retrieval calls RAM recorded for a query — each is a
    separate resource filterable by parentQueryId, so this also works while
    the query is still running (calls appear as RAM persists them)."""
    flt = f"eq(parentQueryId,'{query_id}')"
    results = await asyncio.gather(
        _request("GET", "/toolCalls", params={"filter": flt, "limit": 100}),
        _request("GET", "/llmCalls", params={"filter": flt, "limit": 100}),
        _request("GET", "/retrievalCalls", params={"filter": flt, "limit": 100}),
        return_exceptions=True,
    )

    def _items(r: Any) -> list:
        return [] if isinstance(r, BaseException) or not r else (r.get("items") or [])

    return {"toolCalls": _items(results[0]), "llmCalls": _items(results[1]),
            "retrievalCalls": _items(results[2])}


def _extract_query_id(body: dict | None, resp: httpx.Response | None) -> str | None:
    """An async submit may return the query object, a bare id, or just a
    Location header pointing at the created query — accept any of them."""
    if isinstance(body, dict):
        for key in ("id", "queryId"):
            if body.get(key):
                return str(body[key])
        items = body.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("id"):
            return str(items[0]["id"])
    if isinstance(body, str) and body.strip():
        return body.strip()
    if resp is not None:
        location = resp.headers.get("location") or resp.headers.get("content-location") or ""
        if location:
            return location.rstrip("/").rsplit("/", 1)[-1].split("?")[0] or None
    return None


def _query_finished(q: dict | None) -> bool:
    """A pending async query has errorCode 0 and a null response; it's done
    once RAM writes a response object or a nonzero errorCode."""
    if not q:
        return False
    if q.get("errorCode") or q.get("errorText"):
        return True
    return q.get("response") is not None


async def _fetch_query(query_id: str) -> dict | None:
    """Fetch a single query record. There is no GET /query/{id} item endpoint
    in the v1 API — use the collection endpoint's id filter."""
    body = await _request("GET", "/query", params={"filter": f"eq(id,'{query_id}')", "limit": 1})
    items = body.get("items") or []
    return items[0] if items else None


_TS_KEYS = ("insert_timestamp", "update_timestamp", "insertTimestamp", "updateTimestamp",
            "creationTimeStamp", "creationTimestamp", "modifiedTimeStamp", "createdAt", "created_at",
            "timestamp")
_TS_VALUE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _looks_like_time(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v > 1_000_000_000          # epoch seconds or milliseconds
    return isinstance(v, str) and bool(_TS_VALUE.match(v))


def _query_timestamp(q: dict) -> str:
    """The time a query record carries, whatever RAM calls the field.

    RAM's query records are stamped in snake case (`update_timestamp`), unlike
    its sessions (`insertTimestamp`, `updateTimestamp`); older builds guessed
    camel-case names only, matched nothing, and left history in RAM's own order,
    which is newest first. Try the known names, then any top-level or one-level
    nested field whose name says time or date and whose value looks like one.
    Epoch numbers are zero-padded so they sort with each other."""
    def fmt(v: Any) -> str:
        return f"{int(v):020d}" if isinstance(v, (int, float)) else str(v)
    for k in _TS_KEYS:
        v = q.get(k)
        if _looks_like_time(v):
            return fmt(v)
    for k, v in q.items():
        kl = k.lower()
        if ("time" in kl or "date" in kl) and _looks_like_time(v):
            return fmt(v)
    for v in q.values():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                k2l = k2.lower()
                if ("time" in k2l or "date" in k2l) and _looks_like_time(v2):
                    return fmt(v2)
    return ""


def _normalize_query(q: dict) -> dict:
    """Flatten RAM's queryResponse into the shape the frontend renders."""
    response = q.get("response") or {}
    return {
        "queryId": q.get("id"),
        "querySessionId": q.get("querySessionId"),
        "content": q.get("content"),
        "answer": response.get("answer"),
        "context": response.get("context") or [],
        "toolCalls": response.get("toolCalls") or [],
        "usage": response.get("usageMetadata") or {},
        "target": q.get("target"),
        "targetId": q.get("targetId"),
        "origin": q.get("origin"),
        "parentQueryId": q.get("parentQueryId"),
        "errorCode": q.get("errorCode", 0),
        "errorText": q.get("errorText"),
    }


def status() -> dict:
    if MOCK:
        return {"status": "ok", "mode": "mock", "ramUrl": "(in-memory mock)", "authenticated": True}
    if _static_token():
        auth, authenticated = "static-token", True
    elif _cfg("SAS_CLIENT_ID"):
        auth, authenticated = "oauth", True
    else:
        # Standalone RAM: device sign-in through the UI
        auth = "device"
        e = _peek()
        authenticated = bool(e.get("refresh_token") or (e["token"] and time.time() < e["expires_at"]))
    if not _api_url():
        state = "unconfigured"
    elif auth == "device" and not authenticated:
        state = "signin_required"
    else:
        state = "ok"
    out = {
        "status": state,
        "mode": "live",
        "ramUrl": _api_url() or "(not set)",
        "auth": auth,
        "authenticated": authenticated,
    }
    stamp = session_stamp()
    if stamp is not None:
        out["sessionStamp"] = stamp
    return out


async def status_async() -> dict:
    """status() plus the interactive sign-in flow ("device" or "code")."""
    s = status()
    if s.get("auth") == "device":
        s["signinFlow"] = await detect_signin_flow()
        if s["signinFlow"] == "code":
            s["authorizeUrl"] = viya_authorize_url() if _api_url() else None
    return s


# ─── In-memory mock (RAM_MOCK=true and no RAM address) ───────────────
# Lets the UI run end-to-end without a reachable RAM / Viya environment: two
# agents, two collections, a grounded answer, and (when the question asks for
# one) a chart or a map, so every kind of card can be seen without a live agent.
_MOCK_AGENTS = [
    {"id": "a1000000-0000-0000-0000-000000000001", "name": "Sales Insights Agent",
     "description": "Answers questions on the sales data and draws charts (render_chart)."},
    {"id": "a1000000-0000-0000-0000-000000000002", "name": "Policy Agent",
     "description": "Retrieves and summarizes corporate policy documents."},
    {"id": "a1000000-0000-0000-0000-000000000003", "name": "Mobility Agent",
     "description": "Routes, traffic and places on an interactive map (TomTom MCP)."},
]
_MOCK_COLLECTIONS = [
    {"id": "c1000000-0000-0000-0000-000000000001", "name": "Policy Documents",
     "description": "HR and travel policy PDFs."},
    {"id": "c1000000-0000-0000-0000-000000000002", "name": "Sales Reports",
     "description": "Quarterly sales reports."},
]
_mock_sessions: dict[str, dict] = {}
_mock_traces: dict[str, dict] = {}  # queryId → {"/toolCalls": [...], "/llmCalls": [...], "/retrievalCalls": [...]}

_MOCK_CONTEXT = [{
    "pageContent": (
        "4.2 Travel approval. Trips longer than three working days need the line manager's approval "
        "before booking. Economy class applies to flights under six hours; premium economy may be "
        "booked for longer flights. Expenses are claimed within 30 days of return, with receipts "
        "attached for any single item above 25 USD."
    ),
    "metadata": {"filename": "Travel_Policy_2026.pdf", "page": 7},
}]

_CHART_WORDS = ("chart", "plot", "graph", "compare", "trend", "benchmark", "breakdown", "by region", "by quarter")
_MAP_WORDS = ("map", "route", "traffic", "directions", "navigate", "drive", "nearby", "isochrone")


def _mock_chart_spec() -> dict:
    """A sample `render_chart` spec so the interactive ChartCard renders in
    mock mode. Mirrors the MCP tool's output."""
    return {
        "kind": "chart",
        "type": "bar",
        "title": "Revenue by region — actual vs target (USD m)",
        "data": [
            {"region": "EMEA", "actual": 48.2, "target": 45.0},
            {"region": "Americas", "actual": 61.7, "target": 64.0},
            {"region": "APAC", "actual": 39.4, "target": 36.5},
            {"region": "Middle East", "actual": 27.9, "target": 25.0},
            {"region": "Africa", "actual": 12.6, "target": 14.0},
        ],
        "xKey": "region",
        "yKeys": [{"key": "actual", "label": "Actual"}, {"key": "target", "label": "Target"}],
    }


def _mock_map_spec() -> dict:
    """A sample tomtom-render-map spec (Burj Khalifa → Dubai Marina) so the
    interactive MapCard renders in mock mode. Mirrors the MCP handler output."""
    return {
        "kind": "tomtom.map", "version": 1, "region": "AE",
        "title": "Burj Khalifa → Dubai Marina",
        "center": {"lat": 25.14, "lon": 55.21}, "zoom": 11, "pitch": 45, "bearing": -18,
        "maxBounds": [51.0, 22.5, 56.5, 26.2],
        "markers": [
            {"lat": 25.1972, "lon": 55.2744, "label": "Burj Khalifa", "description": "Downtown Dubai"},
            {"lat": 25.0805, "lon": 55.1403, "label": "Dubai Marina", "description": "Destination"},
            {"lat": 25.1126, "lon": 55.1380, "label": "Mall of the Emirates",
             "category": "Shopping", "color": "#0e7490"},
        ],
        "routes": [{
            "label": "Fastest route", "color": "#0072CE",
            "distanceMeters": 21500, "travelTimeSeconds": 1320,
            "points": [
                {"lat": 25.1972, "lon": 55.2744}, {"lat": 25.1850, "lon": 55.2600},
                {"lat": 25.1500, "lon": 55.2300}, {"lat": 25.1300, "lon": 55.1950},
                {"lat": 25.1100, "lon": 55.1700}, {"lat": 25.0805, "lon": 55.1403},
            ],
        }],
        "incidents": [{
            "lat": 25.1600, "lon": 55.2380, "type": "Accident", "severity": "major",
            "description": "Collision blocking 2 lanes on Sheikh Zayed Road",
        }],
        "areas": [],
        "showTraffic": True, "autoFit": True,
    }


_MOCK_FOOTER = ("_Simulated answer. Set `RAM_API_URL` to your SAS Retrieval Agent Manager address "
                "and restart to talk to your own agents._")


def _mock_answer(content: str, target_name: str) -> tuple[str, list[dict]]:
    """(answer markdown, tool calls with outputs) for a mock query."""
    lc = (content or "").lower()
    if any(w in lc for w in _MAP_WORDS):
        spec = _mock_map_spec()
        return (
            f"**[Mock response from {target_name}]**\n\nThe fastest route from **Burj Khalifa** to "
            "**Dubai Marina** is 21.5 km, about 22 minutes in current traffic. One incident is "
            f"reported on Sheikh Zayed Road.\n\n{_MOCK_FOOTER}",
            [{"toolName": "tomtom-routing",
              "input": {"origin": "Burj Khalifa", "destination": "Dubai Marina"},
              "output": {"summary": {"lengthInMeters": 21500, "travelTimeInSeconds": 1320}}},
             {"toolName": "tomtom-render-map", "input": {"title": spec["title"]}, "output": spec}],
        )
    if any(w in lc for w in _CHART_WORDS):
        spec = _mock_chart_spec()
        return (
            f"**[Mock response from {target_name}]**\n\nThree of the five regions are ahead of target. "
            "**Americas** is the largest at 61.7m but sits 2.3m short of its target, while **APAC** "
            f"leads its target by the widest margin (+2.9m).\n\n{_MOCK_FOOTER}",
            [{"toolName": "query_sales",
              "input": {"measure": "revenue", "group_by": "region", "year": 2026},
              "output": {"rows": len(spec["data"]), "source": "sales_2026"}},
             {"toolName": "render_chart", "input": {"title": spec["title"], "type": "bar"}, "output": spec}],
        )
    return (
        f"**[Mock response from {target_name}]**\n\nYou asked: _{content}_\n\n"
        "Trips longer than three working days need the line manager's approval before booking, and "
        "expenses are claimed within 30 days of return (Travel Policy 2026, p. 7).\n\n"
        "Ask for a **chart** or a **route** to see the interactive cards.\n\n"
        f"{_MOCK_FOOTER}",
        [{"toolName": "retrieve_documents",
          "input": {"query": content, "collection": "Policy Documents"},
          "output": {"documents": 1}}],
    )


async def _mock_request(method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
    params = params or {}
    if path == "/agents":
        return {"items": _MOCK_AGENTS, "count": len(_MOCK_AGENTS)}
    if path == "/collections":
        return {"items": _MOCK_COLLECTIONS, "count": len(_MOCK_COLLECTIONS)}
    if path == "/querySessions" and method == "GET":
        filt = params.get("filter", "")
        if "'" in filt:
            sid = filt.split("'")[1]
            found = [s for s in (_mock_sessions.get(sid),) if s]
            return {"items": [{k: s[k] for k in ("id", "title", "insertTimestamp", "updateTimestamp")} for s in found],
                    "count": len(found)}
        items = sorted(_mock_sessions.values(), key=lambda s: s["updateTimestamp"], reverse=True)
        return {"items": [{k: s[k] for k in ("id", "title", "insertTimestamp", "updateTimestamp")} for s in items],
                "count": len(items)}
    if path.startswith("/querySessions/") and method == "DELETE":
        session = _mock_sessions.pop(path.rsplit("/", 1)[-1], None)
        if session:
            for q in session["queries"]:
                _mock_traces.pop(q["id"], None)
        return None
    if path == "/query" and method == "GET":
        filt = params.get("filter", "")
        if "'" in filt:
            wanted = filt.split("'")[1]
            if filt.startswith("eq(id,"):
                found = [q for s in _mock_sessions.values() for q in s["queries"] if q["id"] == wanted]
                return {"items": found, "count": len(found)}
            session = _mock_sessions.get(wanted, {"queries": []})
            return {"items": session["queries"], "count": len(session["queries"])}
        queries = [q for s in _mock_sessions.values() for q in s["queries"]]
        return {"items": queries, "count": len(queries)}
    if path == "/query" and method == "POST":
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        content = (json or {}).get("content") or ""
        sid = (json or {}).get("querySessionId") or str(uuid.uuid4())
        session = _mock_sessions.setdefault(sid, {
            "id": sid, "title": content[:60], "insertTimestamp": now, "updateTimestamp": now, "queries": [],
        })
        session["updateTimestamp"] = now
        agent_id = (json or {}).get("agentId")
        agent = next((a for a in _MOCK_AGENTS if a["id"] == agent_id), None)
        answer, tool_calls = _mock_answer(content, agent["name"] if agent else "the selected collections")

        query = {
            "id": str(uuid.uuid4()), "content": content, "errorCode": 0, "errorText": None,
            "origin": "user", "querySessionId": sid, "update_timestamp": now,
            "target": "agent" if agent_id else "collection",
            "targetId": {"agentId": agent_id} if agent_id else {"configurationIds": (json or {}).get("collectionIds") or []},
            "response": {
                "answer": answer,
                "context": _MOCK_CONTEXT,
                "toolCalls": tool_calls,
                "usageMetadata": {"llmPromptTokens": 220, "llmCompletionTokens": 96,
                                  "llmTotalTokens": 316, "llmTotalCost": 0.0014},
            },
        }
        session["queries"].append(query)
        _mock_traces[query["id"]] = {
            "/toolCalls": [{
                "id": str(uuid.uuid4()), "parentQueryId": query["id"], "toolName": c["toolName"],
                "input": c["input"], "output": c["output"], "cost": 0,
            } for c in tool_calls],
            "/llmCalls": [{
                "id": str(uuid.uuid4()), "parentQueryId": query["id"], "llmId": "mock-llm",
                "input": {"content": content, "modelName": "gpt-4o", "modelProvider": "azure", "temperature": 0.7},
                "output": {"response": answer, "toolCalls": []},
                "promptTokens": 220, "completionTokens": 96, "promptCost": 0.0008, "completionCost": 0.0006,
            }],
            "/retrievalCalls": [{
                "id": str(uuid.uuid4()), "parentQueryId": query["id"],
                "input": {"query": content, "k": 4, "collection": "Policy Documents"},
                "output": {"documents": 1, "top": "Travel_Policy_2026.pdf p.7"},
            }],
        }
        return query
    if path in ("/toolCalls", "/llmCalls", "/retrievalCalls") and method == "GET":
        filt = params.get("filter", "")
        qid = filt.split("'")[1] if "'" in filt else ""
        return {"items": _mock_traces.get(qid, {}).get(path, [])}
    raise RamError(404, f"Mock has no handler for {method} {path}")
