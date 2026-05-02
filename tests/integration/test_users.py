"""Integration tests for user search and public key endpoints."""

from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, username: str) -> dict:
    payload = {
        "username": username,
        "display_name": username.title(),
        "password": "securepassword1",
        "public_key": f"pubkey-{username}",
        "wrapped_private_key": "wrappedkey==",
        "pbkdf2_salt": "salt==",
    }
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 201
    return resp.json()


class TestUserSearch:
    async def test_search_finds_matching_user(self, client: AsyncClient):
        auth_alice = await _register_and_login(client, "alice_search")
        await _register_and_login(client, "bob_search")

        resp = await client.get(
            "/users/search",
            params={"q": "bob"},
            headers={"Authorization": f"Bearer {auth_alice['access_token']}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert any(u["username"] == "bob_search" for u in results)

    async def test_search_excludes_self(self, client: AsyncClient):
        auth = await _register_and_login(client, "self_search")
        resp = await client.get(
            "/users/search",
            params={"q": "self_search"},
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert resp.status_code == 200
        results = resp.json()
        assert not any(u["username"] == "self_search" for u in results)

    async def test_search_returns_empty_for_no_match(self, client: AsyncClient):
        auth = await _register_and_login(client, "nosearch_user")
        resp = await client.get(
            "/users/search",
            params={"q": "zzznomatch"},
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_search_requires_auth(self, client: AsyncClient):
        # HTTPBearer returns 401 when no Authorization header is present
        resp = await client.get("/users/search", params={"q": "alice"})
        assert resp.status_code == 401

    async def test_search_empty_query_returns_422(self, client: AsyncClient):
        auth = await _register_and_login(client, "qtest_user")
        resp = await client.get(
            "/users/search",
            params={"q": ""},
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert resp.status_code == 422


class TestPublicKey:
    async def test_get_public_key_returns_correct_key(self, client: AsyncClient):
        auth_alice = await _register_and_login(client, "alice_pk")
        bob_auth = await _register_and_login(client, "bob_pk")
        bob_id = bob_auth["user"]["id"]

        resp = await client.get(
            f"/users/{bob_id}/public-key",
            headers={"Authorization": f"Bearer {auth_alice['access_token']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["public_key"] == "pubkey-bob_pk"

    async def test_get_public_key_for_unknown_user_returns_404(
        self, client: AsyncClient
    ):
        auth = await _register_and_login(client, "alice_pk2")
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.get(
            f"/users/{fake_id}/public-key",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert resp.status_code == 404

    async def test_get_public_key_requires_auth(self, client: AsyncClient):
        # HTTPBearer returns 401 when no Authorization header is present
        resp = await client.get(
            "/users/00000000-0000-0000-0000-000000000000/public-key"
        )
        assert resp.status_code == 401
