"""
Pytest fixtures for Jyzrox backend tests.

Strategy:
- Intercept core.database BEFORE main.py imports it (SQLite doesn't support
  pool_size / max_overflow used by production config).
- SQLite in-memory for test DB.
- Mock Redis via AsyncMock.
- Override FastAPI dependencies (get_db, require_auth).
- Patch async_session (used directly by auth routes).
- Disable rate limiting via env var.
"""

import asyncio
import os
import sys
import types as _types
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — must come first
# ---------------------------------------------------------------------------

_backend_dir = str(os.path.join(os.path.dirname(__file__), ".."))
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

# ---------------------------------------------------------------------------
# Environment variables — set BEFORE any app imports
# ---------------------------------------------------------------------------

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["CREDENTIAL_ENCRYPT_KEY"] = "test-key-0123456789abcdef01234567"
os.environ["COOKIE_SECURE"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "false"

# Clear cached settings so env vars take effect
from core.config import get_settings  # noqa: E402

get_settings.cache_clear()

# ---------------------------------------------------------------------------
# Monkey-patch core.database BEFORE it gets imported by routers.
# Production code uses pool_size / max_overflow (invalid for SQLite).
# ---------------------------------------------------------------------------

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase  # noqa: E402


class _PlaceholderBase(DeclarativeBase):
    pass


_placeholder_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_placeholder_factory = async_sessionmaker(_placeholder_engine, class_=AsyncSession, expire_on_commit=False)

# Register `now()` for SQLite (PostgreSQL compat) on the placeholder engine.
# Production code (e.g. verify_api_token) uses raw `now()` in SQL text.
from sqlalchemy import event as _sa_event
from datetime import datetime as _dt
import sqlite3
import uuid

# SQLAlchemy uses UUID(as_uuid=True) for PG but SQLite has no UUID type.
# Override UUID bind processing to store as TEXT strings in SQLite.
sqlite3.register_adapter(uuid.UUID, lambda u: str(u))

from sqlalchemy.dialects.postgresql import UUID as PG_UUID

_original_bind = PG_UUID.bind_processor


def _patched_bind_processor(self, dialect):
    """For non-PG dialects (SQLite), convert UUID to str instead of calling .hex."""
    if dialect.name != "postgresql":
        def process(value):
            if value is not None:
                return str(value) if isinstance(value, uuid.UUID) else value
            return value
        return process
    return _original_bind(self, dialect)


PG_UUID.bind_processor = _patched_bind_processor

_original_result = PG_UUID.result_processor


def _patched_result_processor(self, dialect, coltype):
    """For non-PG dialects (SQLite), convert str back to UUID."""
    if dialect.name != "postgresql":
        def process(value):
            if value is not None and not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value
        return process
    return _original_result(self, dialect, coltype)


PG_UUID.result_processor = _patched_result_processor

# ARRAY → store as JSON text in SQLite
import json as _json
from sqlalchemy import ARRAY as SA_ARRAY

_original_array_bind = SA_ARRAY.bind_processor


def _patched_array_bind(self, dialect):
    if dialect.name != "postgresql":
        def process(value):
            if value is not None:
                return _json.dumps(value) if not isinstance(value, str) else value
            return value
        return process
    return _original_array_bind(self, dialect)


SA_ARRAY.bind_processor = _patched_array_bind

_original_array_result = SA_ARRAY.result_processor


def _patched_array_result(self, dialect, coltype):
    if dialect.name != "postgresql":
        def process(value):
            if value is not None and isinstance(value, str):
                return _json.loads(value)
            return value
        return process
    return _original_array_result(self, dialect, coltype)


SA_ARRAY.result_processor = _patched_array_result

# JSONB → store as JSON text in SQLite
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

_original_jsonb_bind = PG_JSONB.bind_processor


def _patched_jsonb_bind(self, dialect):
    if dialect.name != "postgresql":
        def process(value):
            if value is not None:
                return _json.dumps(value) if not isinstance(value, str) else value
            return value
        return process
    return _original_jsonb_bind(self, dialect)


PG_JSONB.bind_processor = _patched_jsonb_bind

_original_jsonb_result = PG_JSONB.result_processor


def _patched_jsonb_result(self, dialect, coltype):
    if dialect.name != "postgresql":
        def process(value):
            if value is not None and isinstance(value, str):
                return _json.loads(value)
            return value
        return process
    return _original_jsonb_result(self, dialect, coltype)


PG_JSONB.result_processor = _patched_jsonb_result


def _register_sqlite_compat(dbapi_conn, _rec):
    """Register PostgreSQL-compatible functions for SQLite."""
    dbapi_conn.create_function("now", 0, lambda: _dt.now().isoformat())


_sa_event.listen(_placeholder_engine.sync_engine, "connect", _register_sqlite_compat)


async def _fake_get_db():
    async with _placeholder_factory() as session:
        try:
            yield session
        finally:
            await session.close()


# Build fake module and inject BEFORE any router import
_fake_db_mod = _types.ModuleType("core.database")
_fake_db_mod.engine = _placeholder_engine
_fake_db_mod.AsyncSessionLocal = _placeholder_factory
_fake_db_mod.async_session = _placeholder_factory
_fake_db_mod.Base = _PlaceholderBase
_fake_db_mod.AsyncSession = AsyncSession
_fake_db_mod.get_db = _fake_get_db
sys.modules["core.database"] = _fake_db_mod

# ---------------------------------------------------------------------------
# Patch lifespan BEFORE importing main (so app is created with noop lifespan)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(app):
    app.state.arq = AsyncMock()
    app.state.arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job"))
    yield


# Patch at module level so main.py sees it on first import
_lifespan_patch = patch("main.lifespan", _noop_lifespan)
_redis_init_patch = patch("core.redis_client.init_redis", new_callable=AsyncMock)
_redis_close_patch = patch("core.redis_client.close_redis", new_callable=AsyncMock)

# Patch StaticFiles to skip directory check (swagger-ui dir only exists in Docker)
import starlette.staticfiles as _sf_mod
_OrigStaticFiles = _sf_mod.StaticFiles


class _NoCheckStaticFiles(_OrigStaticFiles):
    def __init__(self, **kwargs):
        kwargs.pop("directory", None)
        import tempfile
        kwargs["directory"] = tempfile.mkdtemp()
        super().__init__(**kwargs)


_sf_mod.StaticFiles = _NoCheckStaticFiles

_lifespan_patch.start()
_redis_init_patch.start()
_redis_close_patch.start()

# NOW import main — this happens once, routers register once
import main as _main_mod  # noqa: E402

_app = _main_mod.app

# ---------------------------------------------------------------------------
# Initialize plugins and mount browse routers at module level.
# ASGITransport does NOT trigger lifespan, so we must do this eagerly.
# ---------------------------------------------------------------------------


async def _init_plugins_eager():
    from plugins import init_plugins

    await init_plugins()
    from plugins.registry import plugin_registry

    _BROWSE_PREFIX_MAP = {"ehentai": "/api/eh", "pixiv": "/api/pixiv"}
    for sid, router in plugin_registry.get_browse_routers():
        prefix = _BROWSE_PREFIX_MAP.get(sid, f"/api/browse/{sid}")
        _app.include_router(router, prefix=prefix)


try:
    _loop = asyncio.get_event_loop()
except RuntimeError:
    _loop = asyncio.new_event_loop()

_loop.run_until_complete(_init_plugins_eager())

# ---------------------------------------------------------------------------
# SQLite schema (PostgreSQL-compatible subset)
# ---------------------------------------------------------------------------

_SQLITE_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login_at TIMESTAMP,
        avatar_style TEXT DEFAULT 'gravatar',
        locale TEXT DEFAULT 'en'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS galleries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT,
        title_jpn TEXT,
        category TEXT,
        language TEXT,
        pages INTEGER,
        posted_at TIMESTAMP,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        rating INTEGER DEFAULT 0,
        favorited BOOLEAN DEFAULT 0,
        uploader TEXT,
        parent_id INTEGER REFERENCES galleries(id),
        download_status TEXT DEFAULT 'proxy_only',
        import_mode TEXT,
        tags_array TEXT DEFAULT '[]',
        last_scanned_at TIMESTAMP,
        library_path TEXT,
        artist_id TEXT,
        visibility TEXT DEFAULT 'public',
        created_by_user_id INTEGER REFERENCES users(id),
        source_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blobs (
        sha256 TEXT PRIMARY KEY,
        file_size INTEGER NOT NULL,
        media_type TEXT DEFAULT 'image',
        width INTEGER,
        height INTEGER,
        duration REAL,
        phash TEXT,
        phash_int INTEGER,
        phash_q0 INTEGER,
        phash_q1 INTEGER,
        phash_q2 INTEGER,
        phash_q3 INTEGER,
        extension TEXT NOT NULL,
        storage TEXT DEFAULT 'cas',
        external_path TEXT,
        ref_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        thumbhash TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        page_num INTEGER NOT NULL,
        filename TEXT,
        blob_sha256 TEXT REFERENCES blobs(sha256),
        tags_array TEXT DEFAULT '[]',
        added_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS download_jobs (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        source TEXT,
        status TEXT DEFAULT 'queued',
        progress TEXT DEFAULT '{}',
        error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        next_retry_at TIMESTAMP,
        gallery_id INTEGER REFERENCES galleries(id) ON DELETE SET NULL,
        subscription_id INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS read_progress (
        user_id INTEGER NOT NULL,
        gallery_id INTEGER NOT NULL REFERENCES galleries(id),
        last_page INTEGER DEFAULT 0,
        last_read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, gallery_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blocked_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        namespace TEXT NOT NULL,
        name TEXT NOT NULL,
        UNIQUE (user_id, namespace, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        namespace TEXT NOT NULL,
        name TEXT NOT NULL,
        count INTEGER DEFAULT 0,
        UNIQUE (namespace, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tag_aliases (
        alias_namespace TEXT NOT NULL,
        alias_name TEXT NOT NULL,
        canonical_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (alias_namespace, alias_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tag_implications (
        antecedent_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        consequent_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY (antecedent_id, consequent_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gallery_tags (
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        confidence REAL DEFAULT 1.0,
        source TEXT DEFAULT 'metadata',
        PRIMARY KEY (gallery_id, tag_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_tags (
        image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        confidence REAL,
        PRIMARY KEY (image_id, tag_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credentials (
        source TEXT PRIMARY KEY,
        credential_type TEXT NOT NULL,
        value_encrypted BLOB,
        expires_at TIMESTAMP,
        last_verified TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT,
        token_hash TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used_at TIMESTAMP,
        expires_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS browse_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        title TEXT,
        thumb TEXT,
        gid INTEGER,
        token TEXT,
        viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, source, source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        query TEXT DEFAULT '',
        params TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tag_translations (
        namespace TEXT NOT NULL,
        name TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'zh',
        translation TEXT NOT NULL,
        PRIMARY KEY (namespace, name, language)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS library_paths (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL UNIQUE,
        label TEXT,
        enabled BOOLEAN DEFAULT 1 NOT NULL,
        monitor BOOLEAN DEFAULT 1 NOT NULL,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS plugin_config (
        source_id TEXT PRIMARY KEY,
        enabled BOOLEAN DEFAULT 1,
        config_json TEXT DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT,
        url TEXT NOT NULL,
        source TEXT,
        source_id TEXT,
        avatar_url TEXT,
        enabled BOOLEAN DEFAULT 1,
        auto_download BOOLEAN DEFAULT 1,
        cron_expr TEXT DEFAULT '0 */2 * * *',
        last_checked_at TIMESTAMP,
        last_item_id TEXT,
        last_status TEXT DEFAULT 'pending',
        last_error TEXT,
        next_check_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        batch_total INTEGER DEFAULT 0,
        batch_enqueued INTEGER DEFAULT 0,
        last_job_id TEXT,
        UNIQUE (user_id, url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        cover_gallery_id INTEGER REFERENCES galleries(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_galleries (
        collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        position INTEGER DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (collection_id, gallery_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS excluded_blobs (
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        blob_sha256 TEXT NOT NULL,
        excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (gallery_id, blob_sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blob_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sha_a TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
        sha_b TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
        hamming_dist INTEGER NOT NULL,
        relationship TEXT NOT NULL DEFAULT 'needs_t2',
        suggested_keep TEXT,
        reason TEXT,
        diff_score REAL,
        diff_type TEXT,
        tier INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (sha_a, sha_b)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_favorites (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, gallery_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_ratings (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        gallery_id INTEGER NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL,
        rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, gallery_id)
    )
    """,
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Shared event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    """SQLite in-memory engine with schema, created fresh per test."""
    from datetime import datetime

    # Use shared cache so all connections see the same in-memory DB
    engine = create_async_engine(
        "sqlite+aiosqlite:///file:test?mode=memory&cache=shared&uri=true",
        echo=False,
    )

    # Register PostgreSQL-compatible functions for SQLite
    _sa_event.listen(engine.sync_engine, "connect", _register_sqlite_compat)

    async with engine.begin() as conn:
        for stmt in _SQLITE_SCHEMA:
            await conn.execute(text(stmt.strip()))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Per-test DB session."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def db_session_factory(db_engine):
    """Session factory (mimics async_session used by auth routes)."""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def mock_redis():
    """AsyncMock Redis with common methods pre-configured."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.keys = AsyncMock(return_value=[])
    redis.incr = AsyncMock(return_value=1)
    redis.decr = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=300)
    redis.lpush = AsyncMock(return_value=1)
    redis.lrange = AsyncMock(return_value=[])
    redis.ltrim = AsyncMock(return_value=True)
    redis.scan = AsyncMock(return_value=(0, []))
    return redis


@pytest.fixture
async def client(db_session, db_session_factory, mock_redis):
    """
    Authenticated httpx.AsyncClient.

    get_db and require_auth are overridden so every request is treated
    as user_id=1 with full access.
    """
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 1, "role": "admin"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth

    # Set app.state.arq since ASGITransport doesn't trigger lifespan
    _app.state.arq = AsyncMock()
    _app.state.arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job"))

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.search.async_session", db_session_factory),
        patch("routers.tag.async_session", db_session_factory),
        patch("routers.opds.async_session", db_session_factory),
        patch("routers.history.async_session", db_session_factory),
        patch("routers.external.async_session", db_session_factory),
        patch("routers.export.async_session", db_session_factory),
        patch("routers.settings.async_session", db_session_factory),
        patch("routers.import_router.async_session", db_session_factory),
        patch("routers.artists.async_session", db_session_factory),
        patch("routers.subscriptions.async_session", db_session_factory),
        patch("plugins.builtin.ehentai.browse.async_session", db_session_factory),
        patch("plugins.builtin.ehentai.browse.get_redis", return_value=mock_redis),
        patch("routers.settings.get_redis", return_value=mock_redis),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def unauthed_client(db_session, db_session_factory, mock_redis):
    """
    httpx.AsyncClient WITHOUT auth override.

    Used for login/setup/check/logout tests where we control the session
    cookie manually.
    """
    from httpx import ASGITransport, AsyncClient

    async def _override_get_db():
        yield db_session

    _app.dependency_overrides[_fake_get_db] = _override_get_db

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("plugins.builtin.ehentai.browse.async_session", db_session_factory),
        patch("plugins.builtin.ehentai.browse.get_redis", return_value=mock_redis),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def opds_client(db_session, db_session_factory, mock_redis):
    """
    Authenticated httpx.AsyncClient for OPDS tests.

    Overrides require_opds_auth so every request is treated as user_id=1.
    Patches routers.opds.async_session to use the SQLite test engine.
    """
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_opds_auth

    async def _override_get_db():
        yield db_session

    async def _override_opds_auth():
        return {"user_id": 1}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_opds_auth] = _override_opds_auth

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.opds.async_session", db_session_factory),
        patch("routers.opds.get_redis", return_value=mock_redis),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def unauthed_opds_client(db_session, db_session_factory, mock_redis):
    """
    Unauthenticated httpx.AsyncClient for OPDS auth tests.

    Does NOT override require_opds_auth — callers control auth headers directly.
    Patches routers.opds.async_session to use the SQLite test engine.
    """
    from httpx import ASGITransport, AsyncClient

    async def _override_get_db():
        yield db_session

    _app.dependency_overrides[_fake_get_db] = _override_get_db

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.opds.async_session", db_session_factory),
        patch("routers.opds.get_redis", return_value=mock_redis),
        patch("core.auth.async_session", db_session_factory),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
async def ext_client(db_session, db_session_factory, mock_redis):
    """
    httpx.AsyncClient for external API tests.

    No require_auth override — the external router uses verify_api_token
    (backed by async_session). We patch routers.external.async_session so
    all DB calls go through the SQLite test engine.
    """
    from httpx import ASGITransport, AsyncClient

    async def _override_get_db():
        yield db_session

    _app.dependency_overrides[_fake_get_db] = _override_get_db

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.external.async_session", db_session_factory),
        patch("routers.external.get_redis", return_value=mock_redis),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


@pytest.fixture
def make_client(db_session, db_session_factory, mock_redis):
    """
    Factory that creates an authenticated AsyncClient for any user_id/role.

    Usage (inside an async test):
        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/subscriptions/")

    The two clients cannot be open simultaneously because dependency_overrides
    is global — open one, close it, then open the other.
    """

    @asynccontextmanager
    async def _make(user_id: int, role: str = "member"):
        from httpx import ASGITransport, AsyncClient

        from core.auth import require_auth

        async def _override_get_db():
            yield db_session

        async def _override_require_auth():
            return {"user_id": user_id, "role": role}

        _app.dependency_overrides[_fake_get_db] = _override_get_db
        _app.dependency_overrides[require_auth] = _override_require_auth

        _app.state.arq = AsyncMock()
        _app.state.arq.enqueue_job = AsyncMock(
            return_value=MagicMock(job_id=f"test-job-{user_id}")
        )

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.rate_limit.get_redis", return_value=mock_redis),
            patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
            patch("routers.auth.get_redis", return_value=mock_redis),
            patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
            patch("routers.auth.async_session", db_session_factory),
            patch("routers.search.async_session", db_session_factory),
            patch("routers.tag.async_session", db_session_factory),
            patch("routers.opds.async_session", db_session_factory),
            patch("routers.history.async_session", db_session_factory),
            patch("routers.external.async_session", db_session_factory),
            patch("routers.export.async_session", db_session_factory),
            patch("routers.settings.async_session", db_session_factory),
            patch("routers.import_router.async_session", db_session_factory),
            patch("routers.artists.async_session", db_session_factory),
            patch("routers.subscriptions.async_session", db_session_factory),
            patch("plugins.builtin.ehentai.browse.async_session", db_session_factory),
            patch("plugins.builtin.ehentai.browse.get_redis", return_value=mock_redis),
            patch("routers.settings.get_redis", return_value=mock_redis),
        ):
            transport = ASGITransport(app=_app, raise_app_exceptions=False)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"csrf_token": "test-csrf"},
                headers={"X-CSRF-Token": "test-csrf"},
            ) as ac:
                yield ac

        _app.dependency_overrides.clear()

    return _make


@pytest.fixture
async def hist_client(db_session, db_session_factory, mock_redis):
    """
    Authenticated httpx.AsyncClient for history router tests.

    Patches routers.history.async_session to use the SQLite test engine
    so that history CRUD operations are fully testable in isolation.
    """
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 1, "role": "admin"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.history.async_session", db_session_factory),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()
