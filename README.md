# WhisperBox

End-to-end encrypted instant messaging backend. The server stores only ciphertext — plaintext never leaves the client.

## Quick start

```bash
# 1. Copy env and fill in your values
cp .env.example .env

# 2. Install dependencies
uv sync

# 3. Apply migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload
```

API docs (Stoplight Elements): http://localhost:8000/docs

## Running tests

```bash
uv run pytest                     # all tests
uv run pytest --cov=app           # with coverage
uv run pytest tests/unit          # unit only
uv run pytest tests/integration   # integration only
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

---

> Full architecture diagram, encryption flow, key management explanation, and security trade-offs will be added in the final PR.
