"""Shared FastAPI dependencies."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User

_bearer = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate the Bearer JWT and return the authenticated user.

    Args:
        credentials: HTTP Authorization Bearer header extracted by FastAPI.
        db: Async database session.

    Returns:
        The User record corresponding to the token subject.

    Raises:
        HTTPException: 401 if the token is missing, invalid, or expired.
        HTTPException: 401 if the user no longer exists.
    """
    from app.auth.utils import decode_access_token

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(
        select(User).where(User.id == UUID(user_id), User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


class Pagination:
    """Cursor-based pagination parameters for list endpoints.

    Attributes:
        limit: Maximum number of records to return (1–100, default 50).
        before: Return records created before this ISO-8601 timestamp.
    """

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before: Annotated[str | None, Query()] = None,
    ) -> None:
        self.limit = limit
        self.before = before
