"""OAuth 2.0 PKCE flow for X API and automatic token refresh."""
from __future__ import annotations

import base64
import hashlib
import http.server
import logging
import os
import secrets
import time
import urllib.parse
import webbrowser
from threading import Thread

import httpx
from dotenv import set_key

from .config import get_settings, reload_settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
REDIRECT_URI = "http://127.0.0.1:8080/callback"
SCOPES = "tweet.read users.read bookmark.read offline.access"

_captured_code: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        global _captured_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _captured_code = params["code"][0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<h2>Auth complete. Return to terminal.</h2>")

    def log_message(self, *_: object) -> None:
        pass


def _make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def run_auth_flow() -> None:
    """Interactive PKCE flow — opens the browser and writes tokens to .env."""
    global _captured_code
    _captured_code = None

    cfg = get_settings()
    if not cfg.twitter_client_id:
        raise RuntimeError("TWITTER_CLIENT_ID not set in .env")

    verifier, challenge = _make_pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "response_type": "code",
        "client_id": cfg.twitter_client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    server = http.server.HTTPServer(("127.0.0.1", 8080), _CallbackHandler)
    t = Thread(target=server.handle_request)
    t.start()

    print(f"\nOpening browser for X.com authorization...\n{auth_url}\n")
    webbrowser.open(auth_url)
    t.join(timeout=120)
    server.server_close()

    if not _captured_code:
        raise RuntimeError("No authorization code received within 120s.")

    tokens = _exchange_code(_captured_code, verifier, cfg.twitter_client_id, cfg.twitter_client_secret)
    _persist_tokens(tokens)

    # Fetch and store user ID
    user_id = _fetch_user_id(tokens["access_token"])
    _env_path = _find_env_file()
    set_key(_env_path, "TWITTER_USER_ID", user_id)
    print(f"Stored user ID: {user_id}")

    reload_settings()
    print("Authentication complete. Tokens written to .env")


def _exchange_code(code: str, verifier: str, client_id: str, client_secret: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        auth=(client_id, client_secret),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _fetch_user_id(access_token: str) -> str:
    resp = httpx.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def _persist_tokens(tokens: dict) -> None:
    env_path = _find_env_file()
    set_key(env_path, "TWITTER_ACCESS_TOKEN", tokens["access_token"])
    set_key(env_path, "TWITTER_REFRESH_TOKEN", tokens.get("refresh_token", ""))
    expires_at = str(time.time() + tokens.get("expires_in", 7200))
    set_key(env_path, "TWITTER_TOKEN_EXPIRES_AT", expires_at)


def _find_env_file() -> str:
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(path):
        open(path, "a").close()
    return path


def get_bearer_header() -> dict[str, str]:
    """Return Authorization header, refreshing the token if close to expiry."""
    cfg = get_settings()
    if not cfg.twitter_access_token:
        raise RuntimeError("No access token. Run `xarchiver auth` first.")

    if cfg.twitter_token_expires_at and time.time() > cfg.twitter_token_expires_at - 300:
        logger.info("Access token near expiry, refreshing...")
        _refresh(cfg)

    cfg = reload_settings()
    return {"Authorization": f"Bearer {cfg.twitter_access_token}"}


def _refresh(cfg) -> None:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cfg.twitter_refresh_token,
            "client_id": cfg.twitter_client_id,
        },
        auth=(cfg.twitter_client_id, cfg.twitter_client_secret),
        timeout=15,
    )
    resp.raise_for_status()
    _persist_tokens(resp.json())
    reload_settings()
