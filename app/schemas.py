"""Pydantic v2 request and response schemas.

All schemas use strict validation. Key material fields (public_key,
wrapped_private_key, pbkdf2_salt) are accepted as plain strings because the
backend treats them as opaque base64 blobs — it does not validate encoding.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Shared ────────────────────────────────────────────────────────────────────


class OrmBase(BaseModel):
    """Base model with ORM mode enabled for all response schemas."""

    model_config = ConfigDict(from_attributes=True)


# ── Auth ──────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """Payload for POST /auth/register.

    The frontend generates the RSA-OAEP keypair, wraps the private key with
    AES-KW derived from the user's password via PBKDF2, and sends all key
    material here. The backend hashes the password and stores everything else
    verbatim.
    """

    username: Annotated[str, Field(min_length=3, max_length=32)]
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    password: Annotated[str, Field(min_length=8, max_length=128)]
    public_key: Annotated[str, Field(min_length=1)]
    wrapped_private_key: Annotated[str, Field(min_length=1)]
    pbkdf2_salt: Annotated[str, Field(min_length=1)]

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        """Enforce username format: letters, digits, underscores, hyphens."""
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not all(c in allowed for c in v):
            raise ValueError("username may only contain letters, digits, _ and -")
        return v.lower()


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    username: Annotated[str, Field(min_length=1, max_length=32)]
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RefreshRequest(BaseModel):
    """Payload for POST /auth/refresh."""

    refresh_token: str


class TokenResponse(BaseModel):
    """Access token returned on login and token refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires")


class AuthResponse(BaseModel):
    """Full response for register and login — includes tokens and user profile."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserProfile"


# ── Users ─────────────────────────────────────────────────────────────────────


class UserProfile(OrmBase):
    """Public + private user profile returned to the authenticated user.

    Includes key material (public_key, wrapped_private_key, pbkdf2_salt) so
    the client can reconstruct crypto state on login without needing a
    separate round-trip.
    """

    id: UUID
    username: str
    display_name: str
    public_key: str
    wrapped_private_key: str
    pbkdf2_salt: str
    created_at: datetime


class UserPublicInfo(OrmBase):
    """Minimal user info returned in search results."""

    id: UUID
    username: str
    display_name: str


class UserPublicKey(OrmBase):
    """Single public key response for GET /users/{userId}/public-key."""

    public_key: str


# ── Messages ──────────────────────────────────────────────────────────────────


class EncryptedPayload(BaseModel):
    """The opaque encrypted blob attached to every message.

    The backend stores and forwards this without inspecting any field.
    Field descriptions are provided for frontend intern reference only.
    """

    ciphertext: str = Field(description="Base64-encoded AES-GCM ciphertext")
    iv: str = Field(description="Base64-encoded 96-bit IV (random per message)")
    encrypted_key: str = Field(
        alias="encryptedKey",
        description="Base64-encoded AES key encrypted with recipient's RSA-OAEP public key",
    )
    encrypted_key_for_self: str = Field(
        alias="encryptedKeyForSelf",
        description="Base64-encoded AES key encrypted with sender's RSA-OAEP public key",
    )

    model_config = ConfigDict(populate_by_name=True)


class SendMessageRequest(BaseModel):
    """Payload for POST /messages (offline fallback)."""

    to: UUID = Field(description="Recipient user ID")
    payload: EncryptedPayload


class MessageResponse(OrmBase):
    """A stored message returned from history endpoints or WebSocket delivery."""

    id: UUID
    from_user_id: UUID
    to_user_id: UUID
    payload: dict
    delivered: bool
    created_at: datetime


class ConversationSummary(BaseModel):
    """One entry in the GET /conversations list."""

    user_id: UUID
    display_name: str
    username: str
    last_message_at: datetime | None


# ── WebSocket ─────────────────────────────────────────────────────────────────


class WsMessageSend(BaseModel):
    """Client → Server frame for sending an encrypted message."""

    event: str = "message.send"
    to: UUID
    payload: EncryptedPayload


class WsMessageReceive(BaseModel):
    """Server → Client frame delivering an encrypted message."""

    event: str = "message.receive"
    id: UUID
    from_user_id: UUID
    to_user_id: UUID
    payload: dict
    created_at: datetime


class WsPresence(BaseModel):
    """Server → Client presence notification."""

    event: str = Field(description="'user.online' or 'user.offline'")
    user_id: UUID


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str = "ok"
    environment: str
