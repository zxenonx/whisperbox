"""Users service — search and public key retrieval."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import UserPublicInfo, UserPublicKey


async def search_users(
    query: str, db: AsyncSession, exclude_id: UUID | None = None
) -> list[UserPublicInfo]:
    """Search users by username or display name (case-insensitive prefix match).

    Args:
        query: The search string (minimum 1 character).
        db: Active database session.
        exclude_id: Optional user ID to exclude from results (typically the
            caller's own ID so they don't appear in their own search results).

    Returns:
        Up to 20 matching users as minimal public info records.
    """
    stmt = (
        select(User)
        .where(
            User.deleted_at.is_(None),
            (
                User.username.ilike(f"%{query}%")
                | User.display_name.ilike(f"%{query}%")
            ),
        )
        .limit(20)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)

    result = await db.execute(stmt)
    users = result.scalars().all()
    return [UserPublicInfo.model_validate(u) for u in users]


async def get_public_key(user_id: UUID, db: AsyncSession) -> UserPublicKey:
    """Fetch the RSA-OAEP public key for a given user.

    The client calls this when composing a message to encrypt the AES-GCM
    key for the recipient.

    Args:
        user_id: UUID of the target user.
        db: Active database session.

    Returns:
        The user's base64-encoded RSA-OAEP public key.

    Raises:
        HTTPException: 404 if no active user with *user_id* exists.
    """
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserPublicKey(public_key=user.public_key)
