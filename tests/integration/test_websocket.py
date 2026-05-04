"""Integration tests for the WebSocket endpoint.

Live WebSocket delivery tests use httpx-ws with ASGIWebSocketTransport so they
run fully in-process without a real network socket.

Each test creates its own ASGIWebSocketTransport inside the test function body
so the anyio cancel scope is entered and exited in the same task, avoiding
the "cancel scope in different task" error that occurs when the transport is
managed in a fixture.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws._exceptions import WebSocketDisconnect
from httpx_ws.transport import ASGIWebSocketTransport
from jose import jwt

from app.config import settings
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAYLOAD = {
    "ciphertext": "cipher",
    "iv": "ivdata",
    "encryptedKey": "enckey",
    "encryptedKeyForSelf": "selfkey",
}


async def _register(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/auth/register",
        json={
            "username": username,
            "display_name": username.title(),
            "password": "password123",
            "public_key": f"pubkey-{username}",
            "wrapped_private_key": "wrapkey",
            "pbkdf2_salt": "salt",
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _expired_token(user_id: str) -> str:
    """JWT signed with the app secret but with a past expiry."""
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": user_id, "exp": now - timedelta(hours=1), "iat": now - timedelta(hours=2)},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def _ws_url(token: str | None = None) -> str:
    return f"ws://test/ws?token={token}" if token else "ws://test/ws"


@asynccontextmanager
async def _ws_connect(url: str):
    """In-process WebSocket connection using ASGIWebSocketTransport.

    The transport is created and destroyed within this context manager so the
    anyio cancel scope lives entirely in the calling task — pytest-asyncio
    teardown does not touch it.
    """
    transport = ASGIWebSocketTransport(app=app)
    async with transport:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            async with aconnect_ws(url, c, keepalive_ping_interval_seconds=None) as ws:
                yield ws


def _find_disconnect(exc: BaseException) -> WebSocketDisconnect | None:
    """Recursively extract a WebSocketDisconnect from any exception group nesting."""
    if isinstance(exc, WebSocketDisconnect):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_disconnect(sub)
            if found is not None:
                return found
    return None


async def _expect_close(url: str, expected_code: int) -> None:
    """Assert the server closes the WS with *expected_code*.

    anyio wraps WebSocketDisconnect in nested ExceptionGroups when it bubbles
    out of a task group, so we recurse through the group tree to find it.
    """
    disconnect_code: int | None = None
    try:
        async with _ws_connect(url) as ws:
            await ws.receive_text()
    except (WebSocketDisconnect, BaseExceptionGroup) as exc:
        d = _find_disconnect(exc)
        disconnect_code = d.code if d else None

    assert disconnect_code == expected_code, (
        f"expected close code {expected_code}, got {disconnect_code}"
    )


# ---------------------------------------------------------------------------
# Auth close codes
# ---------------------------------------------------------------------------

class TestWsAuthCloseCodes:
    async def test_valid_token_connects_successfully(self, client: AsyncClient):
        alice = await _register(client, "ws_valid_alice")
        async with _ws_connect(_ws_url(alice["access_token"])):
            pass  # entering and cleanly exiting proves the connection was accepted

    async def test_expired_token_closes_with_4001(self, client: AsyncClient):
        alice = await _register(client, "ws_expired_alice")
        await _expect_close(_ws_url(_expired_token(alice["user"]["id"])), 4001)

    async def test_garbage_token_closes_with_4003(self, client: AsyncClient):
        await _expect_close(_ws_url("notavalidjwt"), 4003)

    async def test_missing_token_closes_with_4003(self, client: AsyncClient):
        await _expect_close(_ws_url(), 4003)

    async def test_tampered_token_closes_with_4003(self, client: AsyncClient):
        alice = await _register(client, "ws_tampered_alice")
        tampered = alice["access_token"][:-4] + "XXXX"
        await _expect_close(_ws_url(tampered), 4003)

    async def test_wrong_secret_token_closes_with_4003(self, client: AsyncClient):
        """A structurally valid JWT signed with the wrong secret is rejected."""
        bad_token = jwt.encode(
            {
                "sub": "00000000-0000-0000-0000-000000000001",
                "exp": datetime.now(UTC) + timedelta(minutes=15),
            },
            "wrong-secret",
            algorithm="HS256",
        )
        await _expect_close(_ws_url(bad_token), 4003)


# ---------------------------------------------------------------------------
# Offline queue
# ---------------------------------------------------------------------------

class TestOfflineQueue:
    async def test_offline_message_shows_as_undelivered(self, client: AsyncClient):
        """REST-sent message is persisted as undelivered (delivered=False)."""
        alice = await _register(client, "alice_offq2")
        bob = await _register(client, "bob_offq2")

        msg_resp = await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": _PAYLOAD},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert msg_resp.status_code == 201
        msg_id = msg_resp.json()["id"]

        history = await client.get(
            f"/conversations/{alice['user']['id']}/messages",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
        )
        msgs = history.json()
        target = next((m for m in msgs if m["id"] == msg_id), None)
        assert target is not None
        assert target["delivered"] is False

    async def test_multiple_offline_messages_all_undelivered(self, client: AsyncClient):
        """Multiple offline messages remain undelivered until WS reconnect."""
        alice = await _register(client, "alice_multi")
        bob = await _register(client, "bob_multi")

        ids = []
        for _ in range(3):
            r = await client.post(
                "/messages",
                json={"to": bob["user"]["id"], "payload": _PAYLOAD},
                headers={"Authorization": f"Bearer {alice['access_token']}"},
            )
            ids.append(r.json()["id"])

        history = await client.get(
            f"/conversations/{alice['user']['id']}/messages",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
        )
        msgs = {m["id"]: m for m in history.json()}
        for msg_id in ids:
            assert msgs[msg_id]["delivered"] is False


# ---------------------------------------------------------------------------
# Presence and payload integrity
# ---------------------------------------------------------------------------

class TestPresenceAndDelivery:
    async def test_send_message_payload_stored_verbatim(self, client: AsyncClient):
        """Payload roundtrips through storage without modification."""
        alice = await _register(client, "alice_rt")
        bob = await _register(client, "bob_rt")

        custom = {
            "ciphertext": "CT",
            "iv": "IV",
            "encryptedKey": "EK",
            "encryptedKeyForSelf": "ESK",
        }
        resp = await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": custom},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 201
        stored = resp.json()["payload"]
        assert stored["ciphertext"] == "CT"
        assert stored["iv"] == "IV"
        assert stored["encryptedKey"] == "EK"
        assert stored["encryptedKeyForSelf"] == "ESK"

    # NOTE: The offline-queue flush on WS connect is covered indirectly:
    # the REST offline-queue tests verify persistence (delivered=False), and
    # the WS router uses AsyncSessionLocal directly rather than the get_db
    # dependency, so it bypasses the test DB override. A proper end-to-end
    # test of the flush path requires a real running server (smoke test).


# ---------------------------------------------------------------------------
# Conversations endpoint (regression for the GREATEST/LEAST fix)
# ---------------------------------------------------------------------------

class TestConversations:
    async def test_empty_conversations_returns_200_empty_list(self, client: AsyncClient):
        """New user with no messages → 200 []."""
        alice = await _register(client, "conv_empty_alice")
        resp = await client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_conversations_lists_partner_after_send(self, client: AsyncClient):
        alice = await _register(client, "conv_send_alice")
        bob = await _register(client, "conv_send_bob")

        await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": _PAYLOAD},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )

        resp = await client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["user_id"] == bob["user"]["id"]
        assert items[0]["username"] == "conv_send_bob"

    async def test_conversations_sorted_by_most_recent(self, client: AsyncClient):
        alice = await _register(client, "conv_sort_alice")
        bob = await _register(client, "conv_sort_bob")
        carol = await _register(client, "conv_sort_carol")

        # Alice → Bob first, then Alice → Carol
        await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": _PAYLOAD},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        await client.post(
            "/messages",
            json={"to": carol["user"]["id"], "payload": _PAYLOAD},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )

        resp = await client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        # Carol was messaged last — must appear first
        assert items[0]["user_id"] == carol["user"]["id"]
        assert items[1]["user_id"] == bob["user"]["id"]

    async def test_conversations_requires_auth(self, client: AsyncClient):
        resp = await client.get("/conversations")
        assert resp.status_code == 401

    async def test_conversations_deduplicates_partner(self, client: AsyncClient):
        """Multiple messages to the same partner yield one conversation entry."""
        alice = await _register(client, "conv_dedup_alice")
        bob = await _register(client, "conv_dedup_bob")

        for _ in range(5):
            await client.post(
                "/messages",
                json={"to": bob["user"]["id"], "payload": _PAYLOAD},
                headers={"Authorization": f"Bearer {alice['access_token']}"},
            )

        resp = await client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_conversations_visible_from_both_sides(self, client: AsyncClient):
        """Recipient also sees the conversation in their list."""
        alice = await _register(client, "conv_both_alice")
        bob = await _register(client, "conv_both_bob")

        await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": _PAYLOAD},
            headers={"Authorization": f"Bearer {alice['access_token']}"},
        )

        bob_resp = await client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
        )
        assert bob_resp.status_code == 200
        items = bob_resp.json()
        assert len(items) == 1
        assert items[0]["user_id"] == alice["user"]["id"]
