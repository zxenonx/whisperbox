"""Auth service — registration, login, token refresh, and logout logic."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.config import settings
from app.models import RefreshToken, User
from app.schemas import AuthResponse, RegisterRequest, TokenResponse, UserProfile


def _as_utc(dt: datetime) -> datetime:
    """Ensure *dt* is timezone-aware UTC (SQLite returns naive datetimes)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


async def register_user(data: RegisterRequest, db: AsyncSession) -> AuthResponse:
    """Create a new user account and issue tokens.

    The password is hashed server-side. All key material (public_key,
    wrapped_private_key, pbkdf2_salt) is stored verbatim — the backend never
    inspects or derives crypto values.

    Args:
        data: Validated registration payload from the client.
        db: Active database session.

    Returns:
        AuthResponse containing access token, refresh token, and user profile.

    Raises:
        HTTPException: 409 if the username is already taken.
    """
    existing = await db.execute(
        select(User).where(User.username == data.username, User.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    user = User(
        username=data.username,
        display_name=data.display_name,
        hashed_password=hash_password(data.password),
        public_key=data.public_key,
        wrapped_private_key=data.wrapped_private_key,
        pbkdf2_salt=data.pbkdf2_salt,
    )
    db.add(user)
    await db.flush()

    access_token, expires_in = create_access_token(str(user.id))
    raw_refresh, refresh_hash = generate_refresh_token()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh_record)
    await db.commit()
    await db.refresh(user)

    return AuthResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=expires_in,
        user=UserProfile.model_validate(user),
    )


async def login_user(username: str, password: str, db: AsyncSession) -> AuthResponse:
    """Authenticate a user and issue new tokens.

    Args:
        username: The login handle submitted by the user.
        password: The raw password submitted by the user.
        db: Active database session.

    Returns:
        AuthResponse containing access token, refresh token, and user profile.

    Raises:
        HTTPException: 401 if credentials are invalid.
    """
    result = await db.execute(
        select(User).where(User.username == username, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(str(user.id))
    raw_refresh, refresh_hash = generate_refresh_token()
    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh_record)
    await db.commit()

    return AuthResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=expires_in,
        user=UserProfile.model_validate(user),
    )


async def refresh_access_token(raw_token: str, db: AsyncSession) -> TokenResponse:
    """Issue a new access token from a valid refresh token.

    Args:
        raw_token: The raw refresh token string sent by the client.
        db: Active database session.

    Returns:
        TokenResponse with a fresh access token.

    Raises:
        HTTPException: 401 if the token is invalid, expired, or revoked.
    """
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()

    if not record or record.revoked or _as_utc(record.expires_at) < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(str(record.user_id))
    return TokenResponse(access_token=access_token, expires_in=expires_in)


async def logout_user(raw_token: str, db: AsyncSession) -> None:
    """Revoke the current refresh token, ending the session.

    Args:
        raw_token: The raw refresh token string sent by the client.
        db: Active database session.

    Note:
        If the token is not found (already expired or invalid), the logout
        is still treated as successful — there is nothing to revoke.
    """
    token_hash = hash_refresh_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if record:
        record.revoked = True
        await db.commit()
