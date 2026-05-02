"""Integration tests for the WebSocket endpoint.

Live WebSocket delivery tests use the WebSocket test client embedded in
Starlette's TestClient, but must share the same event loop as the async
test engine. We therefore keep WS tests minimal and focus on auth rejection
and offline queue behaviour (which is verified via REST history).
"""


from httpx import AsyncClient


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


_PAYLOAD = {
    "ciphertext": "cipher",
    "iv": "ivdata",
    "encryptedKey": "enckey",
    "encryptedKeyForSelf": "selfkey",
}


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

    async def test_multiple_offline_messages_all_undelivered(
        self, client: AsyncClient
    ):
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
