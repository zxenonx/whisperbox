"""WhisperBox FastAPI application entry point.

Mounts all routers and configures middleware. API documentation is served
via Stoplight Elements at /docs instead of the default Swagger UI.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.auth.router import router as auth_router
from app.config import settings
from app.database import Base, engine
from app.messages.router import router as messages_router
from app.schemas import HealthResponse
from app.users.router import router as users_router
from app.websocket.router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Create all tables on startup (development convenience).

    In production, Alembic migrations manage the schema.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="WhisperBox",
    version="0.1.0",
    description=(
        "End-to-end encrypted instant messaging backend. "
        "The server stores only ciphertext — plaintext never leaves the client."
    ),
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
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
