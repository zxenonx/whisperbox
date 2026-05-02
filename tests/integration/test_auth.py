"""Integration tests for auth endpoints."""

from httpx import AsyncClient

_REGISTER_PAYLOAD = {
    "username": "alice_test",
    "display_name": "Alice",
    "password": "securepassword1",
    "public_key": "base64pubkey==",
    "wrapped_private_key": "base64wrappedkey==",
    "pbkdf2_salt": "base64salt==",
}


async def _register(client: AsyncClient, payload: dict | None = None) -> dict:
    resp = await client.post("/auth/register", json=payload or _REGISTER_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()


class TestRegister:
    async def test_register_returns_tokens_and_profile(self, client: AsyncClient):
        data = await _register(client)
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["username"] == "alice_test"
        assert data["user"]["public_key"] == "base64pubkey=="
        assert data["user"]["wrapped_private_key"] == "base64wrappedkey=="
        assert data["user"]["pbkdf2_salt"] == "base64salt=="

    async def test_duplicate_username_returns_409(self, client: AsyncClient):
        await _register(client)
        resp = await client.post("/auth/register", json=_REGISTER_PAYLOAD)
        assert resp.status_code == 409

    async def test_invalid_username_returns_422(self, client: AsyncClient):
        bad = {**_REGISTER_PAYLOAD, "username": "ab"}  # too short
        resp = await client.post("/auth/register", json=bad)
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient):
        await _register(client)
        resp = await client.post(
            "/auth/login",
            json={"username": "alice_test", "password": "securepassword1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_wrong_password(self, client: AsyncClient):
        await _register(client)
        resp = await client.post(
            "/auth/login",
            json={"username": "alice_test", "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_login_unknown_user(self, client: AsyncClient):
        resp = await client.post(
            "/auth/login",
            json={"username": "nobody", "password": "password123"},
        )
        assert resp.status_code == 401


class TestMe:
    async def test_me_returns_profile(self, client: AsyncClient):
        auth = await _register(client)
        resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "alice_test"
        assert "wrapped_private_key" in data

    async def test_me_without_token_returns_401(self, client: AsyncClient):
        # HTTPBearer returns 401 when no Authorization header is present
        resp = await client.get("/auth/me")
        assert resp.status_code == 401

    async def test_me_with_invalid_token_returns_401(self, client: AsyncClient):
        resp = await client.get(
            "/auth/me", headers={"Authorization": "Bearer not.a.real.token"}
        )
        assert resp.status_code == 401


class TestRefresh:
    async def test_refresh_returns_new_access_token(self, client: AsyncClient):
        auth = await _register(client)
        resp = await client.post(
            "/auth/refresh", json={"refresh_token": auth["refresh_token"]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert len(data["access_token"]) > 0

    async def test_refresh_with_invalid_token_returns_401(self, client: AsyncClient):
        resp = await client.post(
            "/auth/refresh", json={"refresh_token": "totally-fake-token"}
        )
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_revokes_refresh_token(self, client: AsyncClient):
        auth = await _register(client)
        # Logout
        resp = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
            json={"refresh_token": auth["refresh_token"]},
        )
        assert resp.status_code == 200

        # Revoked token should no longer work
        resp2 = await client.post(
            "/auth/refresh", json={"refresh_token": auth["refresh_token"]}
        )
        assert resp2.status_code == 401
