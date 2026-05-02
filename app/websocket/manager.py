"""WebSocket connection manager — tracks live connections and routes messages."""

import json
from uuid import UUID

from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections and presence broadcasts.

    Maintains an in-memory map of ``user_id → WebSocket``. When a user
    connects, all other online users receive a ``user.online`` event. When
    they disconnect, all others receive ``user.offline``.

    This is a single-process implementation. For multi-process deployments
    a shared pub/sub backend (Redis) would be needed to broadcast across
    workers.
    """

    def __init__(self) -> None:
        self._active: dict[str, WebSocket] = {}

    async def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        """Register a new connection and broadcast presence.

        Args:
            user_id: UUID of the authenticated user.
            websocket: The accepted WebSocket connection.
        """
        await websocket.accept()
        self._active[str(user_id)] = websocket
        await self._broadcast_presence("user.online", user_id, exclude=user_id)

    def disconnect(self, user_id: UUID) -> None:
        """Deregister a connection (presence broadcast is caller's responsibility).

        Args:
            user_id: UUID of the disconnecting user.
        """
        self._active.pop(str(user_id), None)

    async def broadcast_offline(self, user_id: UUID) -> None:
        """Broadcast a ``user.offline`` event to all remaining connections.

        Args:
            user_id: UUID of the user who disconnected.
        """
        await self._broadcast_presence("user.offline", user_id, exclude=user_id)

    async def send_to(self, user_id: UUID, data: dict) -> bool:
        """Attempt to deliver *data* to *user_id* over their WebSocket.

        Args:
            user_id: Target user UUID.
            data: JSON-serialisable payload to send.

        Returns:
            True if the message was sent to an active connection, False if the
            user is offline (message should remain in the DB as undelivered).
        """
        ws = self._active.get(str(user_id))
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(data))
            return True
        except Exception:
            self._active.pop(str(user_id), None)
            return False

    def is_online(self, user_id: UUID) -> bool:
        """Return True if *user_id* currently has an active connection."""
        return str(user_id) in self._active

    @property
    def online_user_ids(self) -> list[str]:
        """Return the list of currently connected user ID strings."""
        return list(self._active.keys())

    async def _broadcast_presence(
        self, event: str, user_id: UUID, exclude: UUID | None = None
    ) -> None:
        payload = json.dumps({"event": event, "user_id": str(user_id)})
        dead: list[str] = []
        for uid, ws in self._active.items():
            if exclude is not None and uid == str(exclude):
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self._active.pop(uid, None)


manager = ConnectionManager()
