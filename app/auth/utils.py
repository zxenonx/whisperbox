"""Auth utility functions — password hashing and JWT operations."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*.

    Args:
        plain: The raw password string supplied by the user.

    Returns:
        A bcrypt hash string safe for storage.
    """
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check *plain* against a stored bcrypt *hashed* value.

    Args:
        plain: The raw password string to verify.
        hashed: The bcrypt hash stored in the database.

    Returns:
        True if the password matches, False otherwise.
    """
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> tuple[str, int]:
    """Encode a short-lived JWT access token for *user_id*.

    Args:
        user_id: The UUID string of the authenticated user, stored in ``sub``.

    Returns:
        A tuple of (encoded_jwt, expires_in_seconds).
    """
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": user_id, "exp": expire, "iat": datetime.now(UTC)}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, settings.access_token_expire_minutes * 60


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token.

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        The decoded payload dict, or None if the token is invalid or expired.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


def generate_refresh_token() -> tuple[str, str]:
    """Generate a cryptographically secure refresh token and its SHA-256 hash.

    Returns:
        A tuple of (raw_token, sha256_hex_hash). Only the hash is persisted;
        the raw token is returned to the client once and never stored.
    """
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_refresh_token(raw: str) -> str:
    """Compute the SHA-256 hash of a raw refresh token for DB lookup.

    Args:
        raw: The raw refresh token string received from the client.

    Returns:
        The hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(raw.encode()).hexdigest()
