"""Regression: a re-download upsert must not overwrite a manually locked title.

A user title edit writes ``gallery_metadata_field_states(field_name='title',
locked=true)``. The progressive-import ON CONFLICT upsert used to replace the
title regardless. The compiled-SQL shape is covered in ``test_progressive.py``;
this file runs the real statement because EXISTS/CASE correlation and
``excluded`` handling are invisible to SQLite (BE-T25). Skipped unless a server
is given:

    JYZROX_TEST_PG_DSN=postgresql://postgres:test@127.0.0.1:55432/postgres \
        .venv/bin/pytest tests/test_title_lock_pg.py

Each test creates and drops its own database on that server.
"""

import os
import uuid
from pathlib import Path

import pytest

_ADMIN_DSN = os.environ.get("JYZROX_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(not _ADMIN_DSN, reason="JYZROX_TEST_PG_DSN is not set")

_INIT_SQL = (Path(__file__).resolve().parent.parent.parent / "db" / "init.sql").read_text(encoding="utf-8")


@pytest.fixture
async def db():
    import asyncpg
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    name = f"jyzrox_titlelock_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(_ADMIN_DSN)
    await admin.execute(f'CREATE DATABASE "{name}"')
    dsn = f"{_ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
    engine = None
    try:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(_INIT_SQL)
        finally:
            await conn.close()
        engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def _seed(db, *, locked: bool | None) -> int:
    """Create a gallery titled 'Manual Title'; locked=None means no field-state row."""
    from sqlalchemy import text

    async with db() as session:
        gid = (
            await session.execute(
                text(
                    "INSERT INTO galleries (source, source_id, title, tags_array) "
                    "VALUES ('x', '1', 'Manual Title', '{}') RETURNING id"
                )
            )
        ).scalar_one()
        if locked is not None:
            await session.execute(
                text(
                    "INSERT INTO gallery_metadata_field_states (gallery_id, field_name, origin, locked) "
                    "VALUES (:g, 'title', 'manual', :l)"
                ),
                {"g": gid, "l": locked},
            )
        await session.commit()
    return gid


async def _redownload(db, incoming_title: str) -> str:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from db.models import Gallery
    from worker.progressive import _upsert_metadata_set

    stmt = pg_insert(Gallery).values(source="x", source_id="1", title=incoming_title, tags_array=[])
    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "source_id"],
        set_=_upsert_metadata_set(stmt.excluded, include_title_tags=True),
    ).returning(Gallery.id)
    async with db() as session:
        gid = (await session.execute(stmt)).scalar_one()
        await session.commit()
        return (await session.execute(select(Gallery.title).where(Gallery.id == gid))).scalar_one()


async def test_redownload_upsert_locked_title_is_kept(db):
    await _seed(db, locked=True)
    assert await _redownload(db, "Source Title") == "Manual Title"


async def test_redownload_upsert_unlocked_title_is_replaced(db):
    await _seed(db, locked=False)
    assert await _redownload(db, "Source Title") == "Source Title"


async def test_redownload_upsert_without_field_state_row_replaces_title(db):
    await _seed(db, locked=None)
    assert await _redownload(db, "Source Title") == "Source Title"


async def test_redownload_upsert_blank_incoming_title_keeps_existing_title(db):
    await _seed(db, locked=False)
    assert await _redownload(db, "") == "Manual Title"


async def _source_value(db, gid: int):
    from sqlalchemy import text

    async with db() as session:
        return (
            await session.execute(
                text("SELECT source_value #>> '{}' FROM gallery_metadata_field_states WHERE gallery_id = :g"),
                {"g": gid},
            )
        ).scalar_one_or_none()


async def _record(db, gid: int, title: str | None) -> None:
    from worker.progressive import record_locked_title_source

    async with db() as session:
        await record_locked_title_source(session, gid, title)
        await session.commit()


async def test_redownload_upsert_locked_title_updates_pending_source_value(db):
    """Incoming non-blank title on a locked title is recorded as the pending source diff."""
    gid = await _seed(db, locked=True)
    assert await _redownload(db, "Source Title") == "Manual Title"
    await _record(db, gid, "Source Title")
    assert await _source_value(db, gid) == "Source Title"


async def test_record_locked_title_source_unlocked_row_is_not_touched(db):
    gid = await _seed(db, locked=False)
    await _record(db, gid, "Source Title")
    assert await _source_value(db, gid) is None


async def test_record_locked_title_source_blank_title_leaves_source_value_unchanged(db):
    gid = await _seed(db, locked=True)
    await _record(db, gid, "Source Title")
    await _record(db, gid, "")
    await _record(db, gid, None)
    assert await _source_value(db, gid) == "Source Title"
