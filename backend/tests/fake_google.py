"""A local stand-in for Google's OpenID Connect endpoints, for tests and browser checks.

It behaves like Google where the app depends on it: `/authorize` redirects back with a one-time code and
the `state` it was given; `/token` checks the client id and secret, the redirect URI, and the PKCE
verifier against the challenge, then returns an RS256-signed ID token; `/certs` publishes the public key.
The account it signs in as is `FakeGoogle.account` (change it between sign-ins).

Run it on its own for a browser check (then point GOOGLE_*_URL at it):

    python -m tests.fake_google --port 9911 --email you@example.com --name "Your Name"
"""

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
ISSUER = "https://accounts.google.com"


class FakeGoogle:
    def __init__(self, port: int = 0, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET):
        self.client_id, self.client_secret = client_id, client_secret
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = secrets.token_hex(8)
        self.account: dict[str, Any] = {"sub": "1001", "email": "ada@example.com", "name": "Ada Lovelace",
                                         "email_verified": True}  # fmt: skip
        self.codes: dict[str, dict[str, Any]] = {}
        self.token_requests: list[dict[str, str]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    # --- what the app is configured with -------------------------------------------------------
    def env(self) -> dict[str, str]:
        return {"GOOGLE_CLIENT_ID": self.client_id, "GOOGLE_CLIENT_SECRET": self.client_secret,
                "GOOGLE_AUTHORIZE_URL": f"{self.url}/authorize", "GOOGLE_TOKEN_URL": f"{self.url}/token",
                "GOOGLE_JWKS_URL": f"{self.url}/certs"}  # fmt: skip

    def start(self) -> "FakeGoogle":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # --- tokens --------------------------------------------------------------------------------
    def id_token(self, **overrides: Any) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": self.client_id, "iat": now, "exp": now + 3600, **self.account,
                  **overrides}  # fmt: skip
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def issue_code(self, redirect_uri: str, challenge: str, **claims: Any) -> str:
        """A code as /authorize would hand out (for tests that skip the browser redirect)."""
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"redirect_uri": redirect_uri, "challenge": challenge, "claims": claims}
        return code

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        google = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                url = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(url.query))
                if url.path == "/certs":
                    return self._json(200, google.jwks())
                if url.path == "/authorize":
                    if q.get("client_id") != google.client_id or q.get("response_type") != "code":
                        return self._json(400, {"error": "invalid_request"})
                    if q.get("code_challenge_method") != "S256" or "openid" not in q.get("scope", "").split():
                        return self._json(400, {"error": "invalid_request"})
                    code = google.issue_code(q["redirect_uri"], q["code_challenge"])
                    back = f"{q['redirect_uri']}?{urllib.parse.urlencode({'code': code, 'state': q.get('state', '')})}"
                    self.send_response(302)
                    self.send_header("Location", back)
                    self.end_headers()
                    return None
                return self._json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                if self.path != "/token":
                    return self._json(404, {"error": "not_found"})
                length = int(self.headers.get("Content-Length") or 0)
                form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
                google.token_requests.append(form)
                if (
                    form.get("client_id") != google.client_id
                    or form.get("client_secret") != google.client_secret
                ):
                    return self._json(401, {"error": "invalid_client"})
                grant = google.codes.pop(form.get("code", ""), None)  # one use only
                if grant is None or form.get("grant_type") != "authorization_code":
                    return self._json(400, {"error": "invalid_grant", "error_description": "Bad Request"})
                if form.get("redirect_uri") != grant["redirect_uri"]:
                    return self._json(400, {"error": "redirect_uri_mismatch"})
                digest = hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != grant["challenge"]:
                    return self._json(
                        400, {"error": "invalid_grant", "error_description": "Invalid code verifier."}
                    )
                return self._json(200, {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer",
                                        "expires_in": 3599, "id_token": google.id_token(**grant["claims"])})  # fmt: skip

        return Handler


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge), as the web app makes them."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9911)
    ap.add_argument("--email", default="ada@example.com")
    ap.add_argument("--name", default="Ada Lovelace")
    ap.add_argument("--sub", default="1001")
    args = ap.parse_args()
    fake = FakeGoogle(args.port)
    fake.account.update(sub=args.sub, email=args.email, name=args.name)
    print("\n".join(f"{k}={v}" for k, v in fake.env().items()), flush=True)
    fake.server.serve_forever()
