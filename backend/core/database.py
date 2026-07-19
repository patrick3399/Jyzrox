from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias used by routers
async_session = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def advisory_xact_lock(session: AsyncSession, key: int) -> None:
    """Take a transaction-scoped PostgreSQL advisory lock, released on commit/rollback.

    Used to serialize invariant-check-then-act sequences (e.g. "at least one
    admin remains", "no users exist yet") that would otherwise race under
    READ COMMITTED. No-op on non-PostgreSQL backends (e.g. the SQLite engine
    used in tests), which don't support advisory locks and don't run
    concurrent requests against a shared connection in the first place.
    """
    bind = session.get_bind()
    if getattr(bind, "dialect", None) is not None and bind.dialect.name != "postgresql":
        return
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
