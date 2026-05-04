# WhisperBox — API Guide

WhisperBox is an **end-to-end encrypted (E2EE) messaging backend**. The server never sees plaintext — it only stores and forwards encrypted blobs. All encryption and decryption happens on the client.

---

## Base URL

```
https://whisperbox.koyeb.app
```

Interactive API docs (try requests live):

```
https://whisperbox.koyeb.app/docs
```

---

## Authentication

All endpoints except `/auth/register` and `/auth/login` require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

Access tokens expire after **15 minutes**. Use the refresh token to get a new one without logging in again.

---

## Encryption Overview

WhisperBox uses a hybrid encryption scheme — you must implement this on the client before sending or reading messages.

### Key setup (on register)

1. Generate an **RSA-OAEP 2048-bit keypair** on the client
2. Generate a random **128-bit PBKDF2 salt**
3. Derive a wrapping key from the user's password using PBKDF2 → AES-KW
4. Wrap (encrypt) the RSA private key with AES-KW
5. Export the RSA public key as base64
6. Send everything to `POST /auth/register` — the server stores the blobs verbatim

### Restoring session (on login)

1. Call `POST /auth/login` → get back `wrapped_private_key` and `pbkdf2_salt`
2. Re-derive the AES-KW wrapping key from the user's password + salt
3. Unwrap the private key into memory — never store it in plaintext

### Sending a message

1. `GET /users/{recipientId}/public-key` — fetch recipient's RSA-OAEP public key
2. Generate a random **256-bit AES-GCM key** and a **96-bit IV**
3. Encrypt the plaintext with AES-GCM → `ciphertext`
4. Encrypt the AES key with the **recipient's** RSA-OAEP public key → `encryptedKey`
5. Encrypt the AES key with **your own** RSA-OAEP public key → `encryptedKeyForSelf` (so you can read your own sent messages)
6. Send all four values in the `payload` field

### Receiving a message

1. Receive the `payload` blob from the API or WebSocket
2. Decrypt `encryptedKey` with your RSA-OAEP **private key** → AES-GCM key
3. Decrypt `ciphertext` with the AES-GCM key + `iv` → plaintext

---

## Endpoints

### Health

#### `GET /health`

Check if the server is running. No auth required.

**Response**
```json
{ "status": "ok", "environment": "production" }
```

---

### Auth

#### `POST /auth/register`

Create a new account. Returns tokens and the full user profile.

**Request body**
```json
{
  "username": "alice_92",
  "display_name": "Alice",
  "password": "s3cur3P@ssword!",
  "public_key": "<base64 RSA-OAEP public key>",
  "wrapped_private_key": "<base64 AES-KW encrypted private key>",
  "pbkdf2_salt": "<base64 128-bit salt>"
}
```

- `username` — 3–32 chars, letters/digits/`_`/`-` only, stored lowercase
- `password` — 8–128 chars

**Response `201`**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": "uuid",
    "username": "alice_92",
    "display_name": "Alice",
    "public_key": "...",
    "wrapped_private_key": "...",
    "pbkdf2_salt": "...",
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

**Errors:** `409` username taken · `422` validation failed

---

#### `POST /auth/login`

**Request body**
```json
{ "username": "alice_92", "password": "s3cur3P@ssword!" }
```

**Response `200`** — same shape as `/auth/register`

**Errors:** `401` wrong credentials

---

#### `GET /auth/me`

Returns the current user's profile including key material. Call this after login to restore the crypto session.

**Headers:** `Authorization: Bearer <token>`

**Response `200`** — `UserProfile` object (same as the `user` field in login response)

---

#### `POST /auth/refresh`

Get a new access token without logging in again.

**Request body**
```json
{ "refresh_token": "eyJ..." }
```

**Response `200`**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Errors:** `401` refresh token expired or revoked

---

#### `POST /auth/logout`

Revoke the refresh token. The access token expires naturally after 15 minutes.

**Headers:** `Authorization: Bearer <token>`

**Request body**
```json
{ "refresh_token": "eyJ..." }
```

**Response `200`**
```json
{ "detail": "Logged out successfully" }
```

---

### Users

#### `GET /users/search?q=<query>`

Search for users by username or display name (case-insensitive). Returns up to 20 results. You are excluded from your own results.

**Headers:** `Authorization: Bearer <token>`

**Response `200`**
```json
[
  { "id": "uuid", "username": "bob_99", "display_name": "Bob" }
]
```

---

#### `GET /users/{userId}/public-key`

Fetch a user's RSA-OAEP public key. Call this before encrypting a message for them.

**Headers:** `Authorization: Bearer <token>`

**Response `200`**
```json
{ "public_key": "<base64 RSA-OAEP public key>" }
```

**Errors:** `404` user not found

---

### Messages

#### `GET /conversations`

List all conversations, sorted by most recent message first.

**Headers:** `Authorization: Bearer <token>`

**Response `200`**
```json
[
  {
    "user_id": "uuid",
    "display_name": "Bob",
    "username": "bob_99",
    "last_message_at": "2026-01-01T12:00:00Z"
  }
]
```

---

#### `GET /conversations/{userId}/messages`

Get paginated message history with a specific user. Messages are returned **newest first**.

**Headers:** `Authorization: Bearer <token>`

**Query params**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `50` | Max messages per page (1–100) |
| `before` | ISO-8601 string | — | Cursor for pagination — returns messages older than this timestamp |

**Response `200`**
```json
[
  {
    "id": "uuid",
    "from_user_id": "uuid",
    "to_user_id": "uuid",
    "payload": {
      "ciphertext": "...",
      "iv": "...",
      "encryptedKey": "...",
      "encryptedKeyForSelf": "..."
    },
    "delivered": true,
    "created_at": "2026-01-01T12:00:00Z"
  }
]
```

**Pagination example**
```
GET /conversations/{userId}/messages?limit=20
→ get the 20 newest messages

GET /conversations/{userId}/messages?limit=20&before=2026-01-01T12:00:00Z
→ get the 20 messages before that timestamp
```

---

#### `POST /messages` — offline fallback

Use this when a WebSocket connection is not available. The message is stored and delivered to the recipient on their next WebSocket reconnect. **Prefer the WebSocket for real-time delivery.**

**Headers:** `Authorization: Bearer <token>`

**Request body**
```json
{
  "to": "<recipient UUID>",
  "payload": {
    "ciphertext": "<base64 AES-GCM ciphertext>",
    "iv": "<base64 96-bit IV>",
    "encryptedKey": "<base64 RSA-OAEP key for recipient>",
    "encryptedKeyForSelf": "<base64 RSA-OAEP key for sender>"
  }
}
```

**Response `201`** — `MessageResponse` object (same shape as history items)

**Errors:** `400` can't message yourself · `404` recipient not found

---

### WebSocket — Real-time Messaging

#### `WS /ws?token=<access_token>`

Connect with your JWT in the query string (browsers don't support custom headers on WebSocket upgrades).

```
wss://whisperbox.koyeb.app/ws?token=eyJ...
```

On connect, any undelivered messages are flushed to you immediately before the connection is fully open.

---

#### Client → Server events

**`message.send`** — send an encrypted message

```json
{
  "event": "message.send",
  "to": "<recipient UUID>",
  "payload": {
    "ciphertext": "<base64>",
    "iv": "<base64>",
    "encryptedKey": "<base64>",
    "encryptedKeyForSelf": "<base64>"
  }
}
```

---

#### Server → Client events

**`message.receive`** — a message arrived for you

```json
{
  "event": "message.receive",
  "id": "uuid",
  "from_user_id": "uuid",
  "to_user_id": "uuid",
  "payload": { "ciphertext": "...", "iv": "...", "encryptedKey": "...", "encryptedKeyForSelf": "..." },
  "created_at": "2026-01-01T12:00:00Z"
}
```

**`user.online`** / **`user.offline`** — presence notifications

```json
{ "event": "user.online",  "user_id": "uuid" }
{ "event": "user.offline", "user_id": "uuid" }
```

**`error`** — something went wrong with your frame

```json
{ "event": "error", "detail": "Invalid JSON" }
```

---

#### WebSocket close codes

The server always accepts the WebSocket handshake before sending a close frame, so the close code is always visible to the client (not hidden behind an HTTP 403).

| Code | Meaning | What to do |
|---|---|---|
| `4001` | Access token **expired** | Call `POST /auth/refresh` to get a new token, then reconnect |
| `4003` | Token **missing or invalid** | Token was tampered or was never valid — redirect to login |

**Reconnect pattern (recommended)**

```
WS closed with 4001
  → POST /auth/refresh   (use stored refresh token)
  → if 200: reconnect with new access_token
  → if 401: redirect to login (refresh token also expired)

WS closed with 4003
  → redirect to login immediately (do not retry)
```

> Access tokens expire after **15 minutes**. Proactively refresh (e.g. at the 14-minute mark) rather than waiting for the 4001 close to avoid interrupting the connection.

---

## Typical Client Flow

```
1.  Register  →  POST /auth/register          (generate keys client-side first)
2.  Login     →  POST /auth/login             (unwrap private key into memory)
3.  Find user →  GET  /users/search?q=bob
4.  Get key   →  GET  /users/{bobId}/public-key
5.  Connect   →  WS   /ws?token=...
6.  Send      →  WS frame  message.send       (encrypt AES key with Bob's RSA key)
7.  Receive   →  WS frame  message.receive    (decrypt AES key with your RSA key)
8.  History   →  GET  /conversations/{bobId}/messages
9.  Refresh   →  POST /auth/refresh           (when access token nears expiry)
10. Logout    →  POST /auth/logout
```

---

## Quick Reference

| Method | Path | Token required | Description |
|---|---|---|---|
| GET | `/health` | No | Server health |
| POST | `/auth/register` | No | Create account |
| POST | `/auth/login` | No | Log in |
| GET | `/auth/me` | Yes | Current user profile |
| POST | `/auth/refresh` | No | Refresh access token |
| POST | `/auth/logout` | Yes | Revoke refresh token |
| GET | `/users/search?q=` | Yes | Search users |
| GET | `/users/{id}/public-key` | Yes | Get user's RSA public key |
| GET | `/conversations` | Yes | List conversations |
| GET | `/conversations/{id}/messages` | Yes | Message history (paginated) |
| POST | `/messages` | Yes | Send message (offline fallback) |
| WS | `/ws?token=` | Yes | Real-time messaging |
