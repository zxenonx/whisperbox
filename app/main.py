"""WhisperBox FastAPI application entry point.

Mounts all routers and configures middleware. API documentation is served
via Stoplight Elements at /docs instead of the default Swagger UI.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import OperationalError

from app.auth.router import router as auth_router
from app.config import settings
from app.database import Base, engine
from app.messages.router import router as messages_router
from app.schemas import HealthResponse
from app.users.router import router as users_router
from app.websocket.router import router as ws_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except OperationalError as exc:
        # Another worker already created the tables — safe to continue.
        logger.warning("Table creation skipped: %s", exc.orig)
    yield
    await engine.dispose()


app = FastAPI(
    title="WhisperBox",
    version="0.1.0",
    description="""
End-to-end encrypted instant messaging backend. The server stores only ciphertext — plaintext never leaves the client.

---

## How it works

WhisperBox uses a **hybrid encryption** scheme:

- Each message is encrypted with a random **AES-GCM 256-bit key** (fast symmetric encryption).
- That AES key is then encrypted with the **recipient's RSA-OAEP public key** so only they can decrypt it.
- A second copy of the AES key is encrypted with the **sender's own public key** so they can read their own sent messages.
- The server stores and forwards the encrypted blobs without ever seeing plaintext.

---

## Typical flow

### 1. Register
Generate an RSA-OAEP keypair and a PBKDF2 salt on the client. Derive an AES-KW wrapping key from the user's password and use it to wrap the RSA private key. Send the public key, wrapped private key, and salt to `POST /auth/register`. You get back an access token, a refresh token, and the user profile.

### 2. Log in
Call `POST /auth/login`. The response includes `wrapped_private_key` and `pbkdf2_salt` — use these to re-derive the wrapping key from the password and unwrap the RSA private key back into memory. Never persist the private key in plaintext.

### 3. Find someone to message
Use `GET /users/search?q=name` to find a user, then `GET /users/{userId}/public-key` to retrieve their RSA-OAEP public key.

### 4. Connect via WebSocket
Open `wss://whisperbox.koyeb.app/ws?token=<access_token>`. On connect the server immediately flushes any messages that arrived while you were offline.

### 5. Send a message
Generate a random AES-GCM key and IV. Encrypt your plaintext. Encrypt the AES key with the recipient's public key (`encryptedKey`) and again with your own public key (`encryptedKeyForSelf`). Send all four values as the `payload` in a `message.send` WebSocket frame. If the WebSocket is unavailable, use the `POST /messages` REST fallback instead — the message will be delivered on the recipient's next reconnect.

### 6. Receive a message
Listen for `message.receive` frames on the WebSocket. Decrypt `encryptedKey` with your RSA private key to recover the AES-GCM key, then decrypt `ciphertext` with that key and the `iv`.

### 7. Load history
`GET /conversations` lists all active threads. `GET /conversations/{userId}/messages` returns paginated history (newest first). Use the `before` query parameter as a cursor to page back through older messages.

### 8. Keep the session alive
Access tokens expire after **15 minutes**. Call `POST /auth/refresh` with the refresh token to get a new access token without logging in again. On logout, call `POST /auth/logout` to revoke the refresh token.

---

## Authentication

All endpoints except `/auth/register`, `/auth/login`, and `/auth/refresh` require:

```
Authorization: Bearer <access_token>
```

The WebSocket endpoint cannot use headers — pass the token as a query parameter: `?token=<access_token>`.
""",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(messages_router)
app.include_router(ws_router)


# ── Stoplight Elements docs ───────────────────────────────────────────────────

_ELEMENTS_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
    <title>WhisperBox API Docs</title>
    <script src="https://unpkg.com/@stoplight/elements/web-components.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/@stoplight/elements/styles.min.css" />
  </head>
  <body style="height: 100vh; overflow-y: hidden">
    <elements-api
      apiDescriptionUrl="/openapi.json"
      router="hash"
      layout="sidebar"
      tryItCredentialsPolicy="same-origin"
    />
  </body>
</html>"""


@app.get("/docs", include_in_schema=False)
async def stoplight_elements() -> HTMLResponse:
    """Serve the Stoplight Elements API documentation UI."""
    return HTMLResponse(_ELEMENTS_HTML)


# ── Health check ──────────────────────────────────────────────────────────────


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health check",
    description="Returns 200 OK when the service is running. Used by load balancers and uptime monitors.",
)
async def health() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(environment=settings.environment)
