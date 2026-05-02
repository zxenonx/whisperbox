"""Auth endpoints — register, login, token refresh, logout, and /me."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Create a new account. The client must generate the RSA-OAEP keypair "
        "and PBKDF2 salt locally, wrap the private key with AES-KW, and include "
        "all key material in the request body. The backend hashes the password "
        "with bcrypt and stores the key blobs verbatim — it never derives or "
        "inspects cryptographic values. Returns access + refresh tokens and the "
        "full user profile."
    ),
    responses={
        201: {"description": "User created, tokens issued"},
        409: {"description": "Username already taken"},
        422: {"description": "Validation error (e.g. username too short)"},
    },
)
async def register(
    data: Annotated[
        RegisterRequest,
        Body(
            openapi_examples={
                "alice": {
                    "summary": "Typical registration",
                    "value": {
                        "username": "alice_92",
                        "display_name": "Alice",
                        "password": "s3cur3P@ssword!",
                        "public_key": "<base64 RSA-OAEP public key>",
                        "wrapped_private_key": "<base64 AES-KW blob>",
                        "pbkdf2_salt": "<base64 128-bit salt>",
                    },
                }
            }
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    """Register a new user and return auth tokens."""
    return await service.register_user(data, db)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Log in",
    description=(
        "Authenticate with username and password. Returns new access and refresh "
        "tokens plus the user profile including all key material. The client "
        "should use the returned ``wrapped_private_key`` and ``pbkdf2_salt`` to "
        "re-derive the wrapping key and unwrap the RSA private key into memory."
    ),
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid username or password"},
    },
)
async def login(
    data: Annotated[
        LoginRequest,
        Body(
            openapi_examples={
                "example": {
                    "summary": "Standard login",
                    "value": {"username": "alice_92", "password": "s3cur3P@ssword!"},
                }
            }
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    """Authenticate and return tokens."""
    return await service.login_user(data.username, data.password, db)


@router.get(
    "/me",
    response_model=UserProfile,
    summary="Get current user profile",
    description=(
        "Return the authenticated user's full profile, including key material "
        "(``public_key``, ``wrapped_private_key``, ``pbkdf2_salt``). This is the "
        "only endpoint that returns the wrapped private key — the client should "
        "call this immediately after login to restore the session crypto state."
    ),
    responses={
        200: {"description": "User profile"},
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserProfile:
    """Return the profile of the currently authenticated user."""
    return UserProfile.model_validate(current_user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description=(
        "Exchange a valid refresh token for a new short-lived access token. "
        "The refresh token is **not** rotated — the same token remains valid "
        "until it expires or is revoked via ``POST /auth/logout``."
    ),
    responses={
        200: {"description": "New access token issued"},
        401: {"description": "Refresh token is invalid, expired, or revoked"},
    },
)
async def refresh(
    data: Annotated[RefreshRequest, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Issue a new access token from a valid refresh token."""
    return await service.refresh_access_token(data.refresh_token, db)


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Log out",
    description=(
        "Revoke the current refresh token. The access token remains valid until "
        "it expires naturally (15 minutes). To log out immediately on all tabs, "
        "the client should also clear the access token from memory."
    ),
    responses={
        200: {"description": "Logged out successfully"},
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def logout(
    current_user: Annotated[User, Depends(get_current_user)],
    data: Annotated[RefreshRequest, Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Revoke the refresh token and end the session."""
    await service.logout_user(data.refresh_token, db)
    return {"detail": "Logged out successfully"}
