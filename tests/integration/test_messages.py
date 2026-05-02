"""Integration tests for message and conversation endpoints."""

from httpx import AsyncClient

_PAYLOAD = {
    "ciphertext": "abc123",
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


def _auth_header(auth: dict) -> dict:
    return {"Authorization": f"Bearer {auth['access_token']}"}


class TestSendMessage:
    async def test_send_message_stores_and_returns_message(self, client: AsyncClient):
        alice = await _register(client, "alice_msg")
        bob = await _register(client, "bob_msg")

        resp = await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": _PAYLOAD},
            headers=_auth_header(alice),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["from_user_id"] == alice["user"]["id"]
        assert data["to_user_id"] == bob["user"]["id"]
        assert data["payload"]["ciphertext"] == "abc123"
        assert data["delivered"] is False

    async def test_send_to_self_returns_400(self, client: AsyncClient):
        alice = await _register(client, "alice_self")
        resp = await client.post(
            "/messages",
            json={"to": alice["user"]["id"], "payload": _PAYLOAD},
            headers=_auth_header(alice),
        )
        assert resp.status_code == 400

    async def test_send_to_unknown_recipient_returns_404(self, client: AsyncClient):
        alice = await _register(client, "alice_404")
        resp = await client.post(
            "/messages",
            json={
                "to": "00000000-0000-0000-0000-000000000000",
                "payload": _PAYLOAD,
            },
            headers=_auth_header(alice),
        )
        assert resp.status_code == 404

    async def test_send_message_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/messages",
            json={"to": "00000000-0000-0000-0000-000000000001", "payload": _PAYLOAD},
        )
        assert resp.status_code == 401


class TestConversationHistory:
    async def test_get_messages_returns_history(self, client: AsyncClient):
        alice = await _register(client, "alice_hist")
        bob = await _register(client, "bob_hist")

        for _ in range(3):
            await client.post(
                "/messages",
                json={"to": bob["user"]["id"], "payload": _PAYLOAD},
                headers=_auth_header(alice),
            )

        resp = await client.get(
            f"/conversations/{bob['user']['id']}/messages",
            headers=_auth_header(alice),
        )
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 3
        assert all(m["from_user_id"] == alice["user"]["id"] for m in msgs)

    async def test_get_messages_respects_limit(self, client: AsyncClient):
        alice = await _register(client, "alice_limit")
        bob = await _register(client, "bob_limit")

        for _ in range(5):
            await client.post(
                "/messages",
                json={"to": bob["user"]["id"], "payload": _PAYLOAD},
                headers=_auth_header(alice),
            )

        resp = await client.get(
            f"/conversations/{bob['user']['id']}/messages",
            params={"limit": 2},
            headers=_auth_header(alice),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_messages_unknown_partner_returns_404(self, client: AsyncClient):
        alice = await _register(client, "alice_nop")
        resp = await client.get(
            "/conversations/00000000-0000-0000-0000-000000000000/messages",
            headers=_auth_header(alice),
        )
        assert resp.status_code == 404

    async def test_payload_is_opaque_blob(self, client: AsyncClient):
        """Server returns the payload exactly as stored — no modification."""
        alice = await _register(client, "alice_opaque")
        bob = await _register(client, "bob_opaque")
        custom_payload = {
            "ciphertext": "CIPHER",
            "iv": "IV",
            "encryptedKey": "EKEY",
            "encryptedKeyForSelf": "SELFKEY",
        }
        await client.post(
            "/messages",
            json={"to": bob["user"]["id"], "payload": custom_payload},
            headers=_auth_header(alice),
        )
        resp = await client.get(
            f"/conversations/{bob['user']['id']}/messages",
            headers=_auth_header(alice),
        )
        returned = resp.json()[0]["payload"]
        assert returned["ciphertext"] == "CIPHER"
        assert returned["iv"] == "IV"
        assert returned["encryptedKey"] == "EKEY"
        assert returned["encryptedKeyForSelf"] == "SELFKEY"
