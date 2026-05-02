"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas import EncryptedPayload, LoginRequest, RegisterRequest


class TestRegisterRequest:
    def test_valid_request(self):
        req = RegisterRequest(
            username="alice_92",
            display_name="Alice",
            password="password123",
            public_key="base64pubkey",
            wrapped_private_key="base64wrappedprivkey",
            pbkdf2_salt="base64salt",
        )
        assert req.username == "alice_92"

    def test_username_lowercased(self):
        req = RegisterRequest(
            username="ALICE",
            display_name="Alice",
            password="password123",
            public_key="pk",
            wrapped_private_key="wpk",
            pbkdf2_salt="salt",
        )
        assert req.username == "alice"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="ab",
                display_name="Alice",
                password="password123",
                public_key="pk",
                wrapped_private_key="wpk",
                pbkdf2_salt="salt",
            )

    def test_username_too_long(self):
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="a" * 33,
                display_name="Alice",
                password="password123",
                public_key="pk",
                wrapped_private_key="wpk",
                pbkdf2_salt="salt",
            )

    def test_username_invalid_characters(self):
        with pytest.raises(ValidationError, match="letters, digits"):
            RegisterRequest(
                username="ali ce",
                display_name="Alice",
                password="password123",
                public_key="pk",
                wrapped_private_key="wpk",
                pbkdf2_salt="salt",
            )

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="alice",
                display_name="Alice",
                password="short",
                public_key="pk",
                wrapped_private_key="wpk",
                pbkdf2_salt="salt",
            )

    def test_missing_public_key(self):
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="alice",
                display_name="Alice",
                password="password123",
                wrapped_private_key="wpk",
                pbkdf2_salt="salt",
            )


class TestEncryptedPayload:
    def test_camel_case_aliases_accepted(self):
        payload = EncryptedPayload.model_validate(
            {
                "ciphertext": "abc",
                "iv": "def",
                "encryptedKey": "ghi",
                "encryptedKeyForSelf": "jkl",
            }
        )
        assert payload.encrypted_key == "ghi"
        assert payload.encrypted_key_for_self == "jkl"

    def test_snake_case_names_also_accepted(self):
        payload = EncryptedPayload(
            ciphertext="abc",
            iv="def",
            encrypted_key="ghi",
            encrypted_key_for_self="jkl",
        )
        assert payload.ciphertext == "abc"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            EncryptedPayload(ciphertext="abc", iv="def", encrypted_key="ghi")


class TestLoginRequest:
    def test_valid(self):
        req = LoginRequest(username="alice", password="secret123")
        assert req.username == "alice"

    def test_empty_username(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="", password="secret123")
