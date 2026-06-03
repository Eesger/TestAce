"""OAuth 2.0 PKCE flow for X API and automatic token refresh."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
import urllib.parse

import httpx
from dotenv import set_key

from .config import get_settings, reload_settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
REDIRECT_URI = "http://127.0.0.1:8080/callback"
SCOPES = "tweet.read users.read bookmark.read offline.access"


def _make_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def run_auth_flow() -> None:
    """Manual PKCE flow — prints the URL, user pastes back the callback URL."""
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

    print("\n" + "=" * 60)
    print("Stap 1 — Open deze URL in je browser (zorg dat je ingelogd")
    print("         bent met je PERSOONLIJKE X account):")
    print()
    print(auth_url)
    print()
    print("Stap 2 — Klik op 'Authorize app' in de browser.")
    print()
    print("Stap 3 — De browser probeert door te sturen naar")
    print("         http://127.0.0.1:8080/callback?code=...")
    print("         De pagina laadt NIET — dat is normaal.")
    print("         Kopieer de volledige URL uit de adresbalk.")
    print("=" * 60 + "\n")

    raw = input("Plak hier de volledige callback URL: ").strip()

    # Accept either the full URL or just the bare code
    if raw.startswith("http"):
        parsed = urllib.parse.urlparse(raw)
        params_cb = urllib.parse.parse_qs(parsed.query)
        code = params_cb.get("code", [None])[0]
    else:
        code = raw  # user pasted just the code value

    if not code:
        raise RuntimeError(
            "Geen code gevonden in de URL. "
            "Zorg dat je de volledige URL kopieert inclusief '?code=...'."
        )

    print("\nTokens ophalen bij X...")
    tokens = _exchange_code(code, verifier, cfg.twitter_client_id, cfg.twitter_client_secret)
    _persist_tokens(tokens)

    user_id = _fetch_user_id(tokens["access_token"])
    set_key(_find_env_file(), "TWITTER_USER_ID", user_id)

    reload_settings()
    print(f"Klaar! User ID {user_id} opgeslagen in .env")
    print("Je kunt nu 'xarchiver sync' uitvoeren.")



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
