"""SQLAlchemy ORM models.

All primary keys are UUID v7 (time-ordered).
All tables carry ``created_at``, ``updated_at``, and ``deleted_at`` columns.
The backend never stores plaintext message content — ``Message.payload``
is an opaque JSON blob whose inner structure is owned entirely by the client.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

from app.database import Base


class UUIDType(TypeDecorator):
    """Store UUIDs as CHAR(36) on SQLite and native UUID on PostgreSQL."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return uuid.UUID(str(value)) if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return uuid.UUID(str(value))


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    """Mixin that adds created_at, updated_at, and deleted_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now_utc,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now_utc,
        onupdate=_now_utc,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class User(TimestampMixin, Base):
    """Registered user.

    The ``public_key``, ``wrapped_private_key``, and ``pbkdf2_salt`` fields
    are all base64-encoded blobs generated entirely on the client. The backend
    stores them verbatim and returns them on login so the client can reconstruct
    the session crypto.

    Attributes:
        id: UUID v7 primary key.
        username: Unique login handle (3–32 characters).
        display_name: Human-readable name shown in the UI.
        hashed_password: bcrypt hash of the user's password.
        public_key: Base64-encoded RSA-OAEP 2048-bit public key.
        wrapped_private_key: Base64-encoded AES-KW-wrapped RSA private key.
        pbkdf2_salt: Base64-encoded 128-bit random PBKDF2 salt.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        Index("ix_users_deleted_at", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=_new_uuid
    )
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    wrapped_private_key: Mapped[str] = mapped_column(Text, nullable=False)
    pbkdf2_salt: Mapped[str] = mapped_column(String(64), nullable=False)

    sent_messages: Mapped[list["Message"]] = relationship(
        "Message",
        foreign_keys="Message.from_user_id",
        back_populates="sender",
        lazy="noload",
    )
    received_messages: Mapped[list["Message"]] = relationship(
        "Message",
        foreign_keys="Message.to_user_id",
        back_populates="recipient",
        lazy="noload",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        lazy="noload",
    )


class Message(TimestampMixin, Base):
    """Encrypted message between two users.

    The ``payload`` column is an opaque JSON object — the backend never
    reads or validates its inner fields. Structure (set by the client):

        {
            "ciphertext": "<base64 AES-GCM>",
            "iv": "<base64 96-bit IV>",
            "encryptedKey": "<base64 RSA-OAEP key for recipient>",
            "encryptedKeyForSelf": "<base64 RSA-OAEP key for sender>"
        }

    Attributes:
        id: UUID v7 primary key.
        from_user_id: Sender user ID.
        to_user_id: Recipient user ID.
        payload: Opaque encrypted blob (see above).
        delivered: False until the recipient's WebSocket confirms delivery.
    """

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_from_created", "from_user_id", "created_at"),
        Index("ix_messages_to_created", "to_user_id", "created_at"),
        Index("ix_messages_to_delivered", "to_user_id", "delivered"),
        Index("ix_messages_deleted_at", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=_new_uuid
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    sender: Mapped["User"] = relationship(
        "User", foreign_keys=[from_user_id], back_populates="sent_messages"
    )
    recipient: Mapped["User"] = relationship(
        "User", foreign_keys=[to_user_id], back_populates="received_messages"
    )


class RefreshToken(TimestampMixin, Base):
    """Hashed refresh token record.

    Only the SHA-256 hash is stored — the raw token is returned once on
    issuance and never persisted. Tokens are revoked on logout.

    Attributes:
        id: UUID v7 primary key.
        user_id: Owning user.
        token_hash: SHA-256 hex digest of the raw refresh token.
        expires_at: Token expiry timestamp (UTC).
        revoked: True after explicit logout.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=_new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")


# Keep updated_at current on SQLite (which has no native ON UPDATE trigger).
@event.listens_for(User, "before_update")
@event.listens_for(Message, "before_update")
@event.listens_for(RefreshToken, "before_update")
def _set_updated_at(mapper, connection, target):  # noqa: ARG001
    target.updated_at = _now_utc()
