"""Unit tests for auth utility functions."""

from datetime import UTC, datetime, timedelta

from jose import jwt

from app.auth.utils import (
    create_access_token,
    decode_access_token,
    decode_access_token_ws,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.config import settings


def _make_token(sub: str, *, delta: timedelta) -> str:
    """Build a JWT whose expiry is offset from now by *delta*."""
    now = datetime.now(UTC)
    payload = {"sub": sub, "exp": now + delta, "iat": now}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mysecret")
        assert hashed != "mysecret"

    def test_verify_correct_password(self):
        hashed = hash_password("correct-horse")
        assert verify_password("correct-horse", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-horse")
        assert verify_password("wrong-horse", hashed) is False

    def test_same_password_different_hashes(self):
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2  # bcrypt generates a unique salt each time


class TestJWT:
    def test_create_and_decode_roundtrip(self):
        token, expires_in = create_access_token("user-123")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"

    def test_expires_in_is_positive(self):
        _, expires_in = create_access_token("user-123")
        assert expires_in > 0

    def test_decode_invalid_token_returns_none(self):
        assert decode_access_token("not.a.valid.token") is None

    def test_decode_tampered_token_returns_none(self):
        token, _ = create_access_token("user-123")
        tampered = token[:-4] + "xxxx"
        assert decode_access_token(tampered) is None


class TestDecodeAccessTokenWs:
    """decode_access_token_ws must distinguish expired from invalid tokens."""

    def test_valid_token_returns_payload_and_false(self):
        token = _make_token("user-1", delta=timedelta(minutes=15))
        payload, expired = decode_access_token_ws(token)
        assert payload is not None
        assert payload["sub"] == "user-1"
        assert expired is False

    def test_expired_token_returns_none_and_true(self):
        token = _make_token("user-2", delta=timedelta(hours=-1))
        payload, expired = decode_access_token_ws(token)
        assert payload is None
        assert expired is True

    def test_garbage_string_returns_none_and_false(self):
        payload, expired = decode_access_token_ws("notavalidtoken")
        assert payload is None
        assert expired is False

    def test_tampered_signature_returns_none_and_false(self):
        token = _make_token("user-3", delta=timedelta(minutes=15))
        tampered = token[:-4] + "XXXX"
        payload, expired = decode_access_token_ws(tampered)
        assert payload is None
        assert expired is False

    def test_wrong_secret_returns_none_and_false(self):
        token = jwt.encode(
            {"sub": "user-4", "exp": datetime.now(UTC) + timedelta(minutes=15)},
            "totally-wrong-secret",
            algorithm="HS256",
        )
        payload, expired = decode_access_token_ws(token)
        assert payload is None
        assert expired is False

    def test_token_expiring_in_future_is_not_expired(self):
        token = _make_token("user-5", delta=timedelta(seconds=1))
        _, expired = decode_access_token_ws(token)
        assert expired is False

    def test_token_expired_one_second_ago_is_expired(self):
        token = _make_token("user-6", delta=timedelta(seconds=-1))
        _, expired = decode_access_token_ws(token)
        assert expired is True


class TestRefreshToken:
    def test_generate_returns_two_distinct_strings(self):
        raw, digest = generate_refresh_token()
        assert raw != digest
        assert len(raw) > 0
        assert len(digest) == 64  # SHA-256 hex digest

    def test_hash_is_deterministic(self):
        raw, _ = generate_refresh_token()
        assert hash_refresh_token(raw) == hash_refresh_token(raw)

    def test_different_tokens_different_hashes(self):
        raw1, _ = generate_refresh_token()
        raw2, _ = generate_refresh_token()
        assert hash_refresh_token(raw1) != hash_refresh_token(raw2)

    def test_hash_matches_generated_digest(self):
        raw, digest = generate_refresh_token()
        assert hash_refresh_token(raw) == digest
