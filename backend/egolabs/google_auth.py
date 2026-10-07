"""Google sign-in (OpenID Connect, authorization code flow with PKCE).

The web app sends people to Google and gets a one-time code back on its callback. The API then:

1. exchanges the code at Google's token endpoint, with the client secret (which never reaches the browser);
2. verifies the returned ID token: RS256 signature against Google's published keys, audience (our
   client id), issuer, and expiry;
3. requires a verified email.

The caller finds, links, or creates the account from the claims (see `api/auth.py`).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt

from egolabs.config import get_settings


class GoogleSignInError(Exception):
    """Sign-in with Google didn't succeed; the message is safe to show."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


def configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret and s.google_client_secret.get_secret_value())


def exchange_code(code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
    """Trade the authorization code for Google's tokens (the response holds `id_token`)."""
    s = get_settings()
    assert s.google_client_id and s.google_client_secret
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret.get_secret_value(),
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
    ).encode()
    req = urllib.request.Request(
        s.google_token_url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:  # noqa: S310 (configured https URL)
            return json.load(res)
    except urllib.error.HTTPError as e:
        # 400 invalid_grant: the code was already used, expired, or the redirect URI doesn't match.
        try:
            detail = json.load(e).get("error_description") or ""
        except (ValueError, AttributeError):
            detail = ""
        raise GoogleSignInError(
            "Google didn't accept the sign-in. Try again." + (f" ({detail})" if detail else "")
        ) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise GoogleSignInError("Couldn't reach Google to finish signing in. Try again.") from e


@lru_cache
def _jwks(url: str) -> jwt.PyJWKClient:
    # Keeps Google's keys in memory and refetches when a token names a key it doesn't have (rotation).
    return jwt.PyJWKClient(url, cache_keys=True, timeout=15)


def signing_key(id_token: str) -> Any:
    try:
        return _jwks(get_settings().google_jwks_url).get_signing_key_from_jwt(id_token).key
    except jwt.PyJWKClientError as e:
        raise GoogleSignInError("Couldn't check Google's sign-in token. Try again.") from e


def verify_id_token(id_token: str) -> GoogleIdentity:
    s = get_settings()
    try:
        claims = jwt.decode(
            id_token,
            signing_key(id_token),
            algorithms=["RS256"],
            audience=s.google_client_id,
            options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            leeway=60,
        )
    except jwt.PyJWTError as e:
        raise GoogleSignInError("Google's sign-in token isn't valid. Try again.") from e
    if claims.get("iss") not in s.google_issuers:
        raise GoogleSignInError("Google's sign-in token isn't valid. Try again.")
    email = claims.get("email")
    if not email or claims.get("email_verified") is not True:
        raise GoogleSignInError("Your Google account's email address isn't verified.")
    name = claims.get("name") or None
    return GoogleIdentity(sub=str(claims["sub"]), email=str(email).lower(), name=name)


def sign_in(code: str, redirect_uri: str, code_verifier: str) -> GoogleIdentity:
    tokens = exchange_code(code, redirect_uri, code_verifier)
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str):
        raise GoogleSignInError("Google didn't return a sign-in token. Try again.")
    return verify_id_token(id_token)
