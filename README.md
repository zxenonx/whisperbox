# WhisperBox

End-to-end encrypted instant messaging backend. The server stores **only ciphertext** — plaintext never leaves the client device.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   CLIENT (Next.js)                   │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  Auth Module │  │ Crypto Module│  │  Chat UI  │  │
│  └──────────────┘  └──────────────┘  └───────────┘  │
│                           │                          │
│                    ┌──────▼──────┐                   │
│                    │  API Client │                   │
│                    │  WS Client  │                   │
│                    └──────┬──────┘                   │
└───────────────────────────┼─────────────────────────┘
                            │ HTTPS / WSS
┌───────────────────────────┼─────────────────────────┐
│                   WhisperBox (FastAPI)                │
│                           │                          │
│  ┌──────────┐  ┌──────────┴──┐  ┌────────────────┐  │
│  │   Auth   │  │  WebSocket  │  │  REST Endpoints│  │
│  │  (JWT)   │  │   Manager   │  │ keys, messages │  │
│  └──────────┘  └─────────────┘  └────────────────┘  │
│                                                      │
│          ┌──────────────────────────────┐            │
│          │         Database             │            │
│          │  users (public key,          │            │
│          │         wrapped private key, │            │
│          │         pbkdf2 salt)         │            │
│          │  messages (opaque ciphertext)│            │
│          │  refresh_tokens              │            │
│          └──────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
```

**The server never has access to:**
- Private keys (stored wrapped on the client, never transmitted unwrapped)
- Message plaintext (only the encrypted payload reaches the server)
- The symmetric AES-GCM key used per message

---

## Encryption Flow

### Registration

```
Client                                    Server
  │                                         │
  ├── Generate RSA-OAEP 2048-bit keypair    │
  ├── Generate random 128-bit PBKDF2 salt   │
  ├── Derive wrappingKey via PBKDF2         │
  │   (SHA-256, 310 000 iters, 256-bit)     │
  ├── Wrap private key with AES-KW 256-bit  │
  │                                         │
  ├── POST /auth/register ─────────────────►│
  │   { username, password,                 │  bcrypt hash password
  │     public_key (base64),                │  store public_key verbatim
  │     wrapped_private_key (base64),        │  store wrapped_private_key verbatim
  │     pbkdf2_salt (base64) }              │  store pbkdf2_salt verbatim
  │                                         │
  │◄─────────────────── JWT + user profile ─┤
```

### Login

```
Client                                    Server
  │                                         │
  ├── POST /auth/login ───────────────────►│
  │   { username, password }               │  bcrypt verify
  │                                         │
  │◄─── JWT + { wrapped_private_key,        │
  │             pbkdf2_salt, public_key } ──┤
  │                                         │
  ├── Re-derive wrappingKey (PBKDF2)        │
  ├── Unwrap RSA private key (AES-KW)       │
  ├── Private key loaded into memory only   │
  │   (never written to disk)              │
```

### Sending a Message (Alice → Bob)

```
Alice (client)                            Server            Bob (client)
  │                                         │                   │
  ├── GET /users/{bobId}/public-key ───────►│                   │
  │◄─────────────── Bob's RSA public key ───┤                   │
  │                                         │                   │
  ├── Generate random AES-GCM 256-bit key   │                   │
  ├── Generate random 96-bit IV             │                   │
  ├── Encrypt plaintext → ciphertext        │                   │
  ├── Encrypt AES key with Bob's public key → encryptedKey      │
  ├── Encrypt AES key with own public key → encryptedKeyForSelf │
  │                                         │                   │
  ├── WS message.send ─────────────────────►│                   │
  │   { to: bobId, payload: {               │  store opaque blob│
  │       ciphertext, iv,                   │  route to Bob     │
  │       encryptedKey,                     │                   │
  │       encryptedKeyForSelf } }           ├──── WS message.receive ──►│
  │                                         │                   │
  │                                         │                   ├── Decrypt encryptedKey with own private key → AES key
  │                                         │                   ├── Decrypt ciphertext with AES key + iv → plaintext
  │                                         │                   └── Display message 🔒
```

---

## Key Management

| Key | Generated by | Stored where | Never leaves |
|---|---|---|---|
| RSA-OAEP keypair | Client (registration) | Public key on server; private key never | Client memory |
| PBKDF2 salt | Client (registration) | Server (verbatim) | N/A |
| AES-KW wrapping key | Client (PBKDF2 derivation) | Never stored | Client memory |
| Wrapped RSA private key | Client (AES-KW) | Server (verbatim blob) | Client |
| Per-message AES-GCM key | Client (per message) | Never stored | Client memory |

**Password dual-use**: The user's password is both the authentication credential
(checked server-side via bcrypt) and the input to PBKDF2 for deriving the
AES-KW wrapping key. This means a forgotten password permanently loses access
to all message history — there is no server-side recovery path.

---

## API Reference

Full interactive docs are available at `/docs` (Stoplight Elements) once the server is running.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Register, generate keys, get tokens |
| POST | `/auth/login` | — | Login, get tokens + key material |
| GET | `/auth/me` | Bearer | Full profile + key material |
| POST | `/auth/refresh` | — | Exchange refresh token for new access token |
| POST | `/auth/logout` | Bearer | Revoke refresh token |
| GET | `/users/search?q=` | Bearer | Search users by name |
| GET | `/users/{id}/public-key` | Bearer | Get RSA public key for message encryption |
| GET | `/conversations` | Bearer | List conversation partners |
| GET | `/conversations/{id}/messages` | Bearer | Paginated message history |
| POST | `/messages` | Bearer | Send message (offline REST fallback) |
| WS | `/ws?token=<jwt>` | JWT query | Real-time messaging |

---

## Running Locally

```bash
# 1. Copy and fill in environment config
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, CORS_ORIGINS

# 2. Install dependencies
uv sync

# 3. Apply database migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

For Neon PostgreSQL (production), set:
```
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.neon.tech/whisperbox?sslmode=require
```

---

## Running Tests

```bash
uv run pytest                   # all 55 tests
uv run pytest --cov=app         # with coverage
uv run pytest tests/unit        # unit tests only
uv run pytest tests/integration # integration tests only
```

## Linting

```bash
uv run ruff check .    # lint
uv run ruff format .   # format
```

---

## Security Trade-offs

| Trade-off | Decision |
|---|---|
| Password = key derivation input | Simplifies UX (single credential) but means forgotten password = permanent data loss |
| Refresh token not rotated | Simpler implementation; rotate if replay risk is a concern |
| Single device | Private key lives in one browser's IndexedDB; no multi-device sync |
| No forward secrecy | Each message uses a fresh AES-GCM key but no ratchet — past messages can be decrypted if the RSA private key is compromised |
| In-process WS presence map | Works for a single server process; a Redis pub/sub layer is needed for horizontal scaling |

## Known Limitations

- **Single device**: No key export / import flow for multi-device use
- **No forward secrecy**: A compromised RSA key exposes all past messages
- **No key rotation**: Users cannot re-generate their keypair
- **No message deletion**: Soft-delete fields exist but no API endpoint yet
- **Single process WebSocket**: Presence and delivery require a single uvicorn worker; use a message broker for multi-process deployments
