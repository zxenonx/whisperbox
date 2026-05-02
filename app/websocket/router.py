"""WebSocket endpoint — authenticated real-time message delivery."""

import json
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.auth.utils import decode_access_token
from app.database import AsyncSessionLocal
from app.messages import service as msg_service
from app.schemas import SendMessageRequest, WsMessageReceive
from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


async def _authenticate(token: str | None) -> UUID | None:
    """Decode and validate the JWT from the WebSocket handshake query param.

    Args:
        token: Raw JWT string from the ``?token=`` query parameter.

    Returns:
        The user UUID if the token is valid, None otherwise.
    """
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    return UUID(sub) if sub else None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT access token"),
) -> None:
    """Authenticated WebSocket endpoint for real-time E2EE messaging.

    **Authentication**: Pass the JWT access token as a query parameter:
    ``wss://host/ws?token=<access_token>``

    **Client → Server events**

    | Event | Payload | Description |
    |---|---|---|
    | ``message.send`` | ``{event, to, payload: {ciphertext, iv, encryptedKey, encryptedKeyForSelf}}`` | Send an encrypted message |

    **Server → Client events**

    | Event | Payload | Description |
    |---|---|---|
    | ``message.receive`` | ``{event, id, from_user_id, to_user_id, payload, created_at}`` | Deliver incoming message |
    | ``user.online`` | ``{event, user_id}`` | Another user connected |
    | ``user.offline`` | ``{event, user_id}`` | Another user disconnected |

    **Offline queue**: On connect, all undelivered messages are flushed before
    the socket is ready to accept new sends.

    **Error frame**: ``{"event": "error", "detail": "<reason>"}``
    """
    user_id = await _authenticate(token)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(user_id, websocket)

    async with AsyncSessionLocal() as db:
        # Flush offline queue on reconnect
        undelivered = await msg_service.get_undelivered(user_id, db)
        for msg in undelivered:
            frame = WsMessageReceive(
                event="message.receive",
                id=msg.id,
                from_user_id=msg.from_user_id,
                to_user_id=msg.to_user_id,
                payload=msg.payload,
                created_at=msg.created_at,
            )
            sent = await manager.send_to(user_id, frame.model_dump(mode="json"))
            if sent:
                await msg_service.mark_delivered(msg.id, db)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"event": "error", "detail": "Invalid JSON"})
                )
                continue

            event = data.get("event")

            if event == "message.send":
                await _handle_send(user_id, data, websocket)
            else:
                await websocket.send_text(
                    json.dumps({"event": "error", "detail": f"Unknown event: {event}"})
                )

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        await manager.broadcast_offline(user_id)


async def _handle_send(sender_id: UUID, data: dict, websocket: WebSocket) -> None:
    """Process a ``message.send`` frame from the client.

    Persists the message, then attempts live delivery. If the recipient is
    offline the message stays in the DB with ``delivered=False`` and will be
    flushed on their next reconnect.

    Args:
        sender_id: Authenticated sender's user UUID.
        data: Parsed JSON frame received from the client.
        websocket: The sender's WebSocket (for error responses).
    """
    try:
        req = SendMessageRequest.model_validate(data)
    except Exception as exc:
        await websocket.send_text(
            json.dumps({"event": "error", "detail": f"Invalid payload: {exc}"})
        )
        return

    async with AsyncSessionLocal() as db:
        try:
            stored = await msg_service.store_message(sender_id, req, db)
        except Exception as exc:
            await websocket.send_text(
                json.dumps({"event": "error", "detail": str(exc)})
            )
            return

        frame = WsMessageReceive(
            event="message.receive",
            id=stored.id,
            from_user_id=stored.from_user_id,
            to_user_id=stored.to_user_id,
            payload=stored.payload,
            created_at=stored.created_at,
        )
        delivered = await manager.send_to(
            req.to, frame.model_dump(mode="json")
        )
        if delivered:
            await msg_service.mark_delivered(stored.id, db)
