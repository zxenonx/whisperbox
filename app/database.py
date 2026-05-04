"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_connect_args: dict = {}
if settings.database_url.startswith("postgresql"):
    _connect_args = {"ssl": "require"}

engine = create_async_engine(
    settings.database_url,
    echo=not settings.is_production,
    future=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency that yields a database session per request.

    Yields:
        AsyncSession: An active database session that is closed after the
            request completes, regardless of whether an exception occurred.
    """
    async with AsyncSessionLocal() as session:
        yield session
