"""Message endpoints — conversation list, history, and offline fallback."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.messages import service
from app.models import User
from app.schemas import ConversationSummary, MessageResponse, SendMessageRequest

router = APIRouter(tags=["messages"])


@router.get(
    "/conversations",
    response_model=list[ConversationSummary],
    summary="List conversations",
    description=(
        "Return a summary of all conversations the authenticated user participates in, "
        "ordered by most-recent message first. Each entry includes the partner's ID, "
        "display name, username, and the timestamp of the last message."
    ),
    responses={
        200: {"description": "List of conversation summaries"},
        401: {"description": "Missing or invalid Bearer token"},
    },
)
async def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ConversationSummary]:
    """List all active conversations for the current user."""
    return await service.list_conversations(current_user.id, db)


@router.get(
    "/conversations/{user_id}/messages",
    response_model=list[MessageResponse],
    summary="Get conversation history",
    description=(
        "Return paginated message history between the authenticated user and "
        "``user_id``. Messages are returned newest-first. Use the ``before`` "
        "query parameter (ISO-8601 timestamp) as a cursor to paginate to older "
        "messages. The payload in each message is an opaque encrypted blob — "
        "the client is responsible for decryption."
    ),
    responses={
        200: {"description": "Paginated list of encrypted messages"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Conversation partner not found"},
    },
)
async def get_messages(
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max messages per page")] = 50,
    before: Annotated[
        str | None,
        Query(description="ISO-8601 cursor — return messages older than this timestamp"),
    ] = None,
) -> list[MessageResponse]:
    """Return paginated message history for a conversation."""
    return await service.get_conversation_messages(
        current_user.id, user_id, limit, before, db
    )


@router.post(
    "/messages",
    response_model=MessageResponse,
    status_code=201,
    summary="Send a message (offline fallback)",
    description=(
        "REST fallback for sending an encrypted message when a WebSocket "
        "connection is not available. The server persists the message and "
        "delivers it to the recipient on their next WebSocket reconnect. "
        "For real-time delivery, prefer the ``message.send`` WebSocket event. "
        "The ``payload`` field is treated as an opaque blob — the server stores "
        "it without inspection."
    ),
    responses={
        201: {"description": "Message stored"},
        400: {"description": "Cannot send a message to yourself"},
        401: {"description": "Missing or invalid Bearer token"},
        404: {"description": "Recipient not found"},
    },
)
async def send_message(
    data: Annotated[
        SendMessageRequest,
        Body(
            openapi_examples={
                "example": {
                    "summary": "Encrypted message from Alice to Bob",
                    "value": {
                        "to": "00000000-0000-0000-0000-000000000001",
                        "payload": {
                            "ciphertext": "<base64 AES-GCM ciphertext>",
                            "iv": "<base64 96-bit IV>",
                            "encryptedKey": "<base64 RSA-OAEP key for Bob>",
                            "encryptedKeyForSelf": "<base64 RSA-OAEP key for Alice>",
                        },
                    },
                }
            }
        ),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """Persist an encrypted message (offline delivery fallback)."""
    return await service.store_message(current_user.id, data, db)
