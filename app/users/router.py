"""User endpoints — search and public key retrieval."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import UserPublicInfo, UserPublicKey
from app.users import service

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/search",
    response_model=list[UserPublicInfo],
    summary="Search users",
    description=(
        "Search for users by username or display name (case-insensitive). "
        "Returns up to 20 results. The authenticated user is automatically "
        "excluded from results. Requires a valid Bearer token."
    ),
    responses={
        200: {"description": "List of matching users (may be empty)"},
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def search_users(
    q: Annotated[
        str,
        Query(min_length=1, max_length=64, description="Search string"),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserPublicInfo]:
    """Search users by username or display name."""
    return await service.search_users(q, db, exclude_id=current_user.id)


@router.get(
    "/{user_id}/public-key",
    response_model=UserPublicKey,
    summary="Get a user's public key",
    description=(
        "Retrieve the RSA-OAEP public key for a specific user. The client calls "
        "this before composing a message to encrypt the per-message AES-GCM key "
        "for the recipient. Returns the raw base64-encoded public key."
    ),
    responses={
        200: {"description": "User's RSA-OAEP public key"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "User not found"},
    },
)
async def get_public_key(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPublicKey:
    """Fetch the RSA-OAEP public key for *user_id*."""
    return await service.get_public_key(user_id, db)
