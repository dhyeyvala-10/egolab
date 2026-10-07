import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from egolabs.config import get_settings

_hasher = PasswordHash.recommended()  # Argon2id


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


# Hash of a random password, so login does the same work whether or not the email exists.
DUMMY_HASH = hash_password(uuid.uuid4().hex)


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    settings = get_settings()
    expires_in = settings.jwt_expires_minutes * 60
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=expires_in)},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> uuid.UUID | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None
