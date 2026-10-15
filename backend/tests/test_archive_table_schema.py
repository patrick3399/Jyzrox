"""Regression: every gallery-dl archive table must carry a self-filling job_id.

ProgressiveImporter._link_archive_entries links the rows whose ``job_id`` is
the finishing job. A pre-created table without the column makes that statement
fail, so its entries are never linked to a gallery and survive the gallery's
deletion (instagram: 6017 unlinked rows, 2026-10-08). A column without the
default is never filled — gallery-dl inserts ``entry`` only — which leaves the
rows just as unlinked.
"""

import importlib.util
import re
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_INIT_SQL = (_BACKEND_DIR.parent / "db" / "init.sql").read_text(encoding="utf-8")
_MIGRATION = _BACKEND_DIR / "migrations" / "versions" / "0028_archive_tables_job_id.py"
_MIGRATION_0032 = _BACKEND_DIR / "migrations" / "versions" / "0032_archive_rows_record_their_job.py"

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", re.DOTALL)


def _archive_tables() -> dict[str, str]:
    return {
        name: body
        for name, body in _CREATE_TABLE_RE.findall(_INIT_SQL)
        if re.search(r"^\s*entry\s+TEXT PRIMARY KEY", body, re.M)
    }


def _load_migration(path: Path = _MIGRATION):
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem[:4]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_init_sql_archive_table_without_job_id_is_rejected():
    tables = _archive_tables()
    assert "instagram" in tables
    missing = sorted(name for name, body in tables.items() if not re.search(r"^\s*job_id\s+UUID", body, re.M))
    assert missing == []


def test_migration_0028_adds_job_id_to_every_init_sql_archive_table_idempotently():
    module = _load_migration()
    assert set(_archive_tables()) <= set(module.ARCHIVE_TABLES) | {"exhentai", "pixiv", "twitter", "weibo", "xiuren7"}

    executed: list[str] = []
    module.op = type("Op", (), {"execute": staticmethod(executed.append)})
    module.upgrade()

    for table in module.ARCHIVE_TABLES:
        statement = next(sql for sql in executed if f"ALTER TABLE {table} " in sql)
        assert "ADD COLUMN IF NOT EXISTS job_id UUID" in statement
        assert f"to_regclass('public.{table}') IS NOT NULL" in statement


def test_init_sql_archive_table_whose_job_id_has_no_session_default_is_rejected():
    from plugins.builtin.gallery_dl._archive import ARCHIVE_JOB_ID_DEFAULT

    tables = _archive_tables()
    assert "twitter" in tables
    unstamped = sorted(name for name, body in tables.items() if f"UUID DEFAULT {ARCHIVE_JOB_ID_DEFAULT}," not in body)
    assert unstamped == []


def test_migration_0032_sets_the_same_job_id_default_as_init_sql():
    from plugins.builtin.gallery_dl._archive import ARCHIVE_JOB_ID_DEFAULT

    module = _load_migration(_MIGRATION_0032)
    executed: list[str] = []
    module.op = type("Op", (), {"execute": staticmethod(executed.append)})
    module.upgrade()

    (statement,) = executed
    # The default sits inside a format() literal, so its quotes are doubled.
    assert "ALTER COLUMN job_id " in statement
    assert "SET DEFAULT " + ARCHIVE_JOB_ID_DEFAULT.replace("'", "''") in statement
    assert "information_schema.tables" in statement


async def test_archive_table_created_by_gallery_dl_gets_the_job_id_default_at_startup():
    """gallery-dl creates a table for an unregistered category as (entry) only."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import worker
    from plugins.builtin.gallery_dl._archive import ARCHIVE_JOB_ID_DEFAULT

    session = AsyncMock()
    session.execute.side_effect = [
        [("newsite",)],  # tables with entry but no gallery_id
        None,  # advisory lock
        MagicMock(first=MagicMock(return_value=("r", ["entry"]))),
        None,  # lock_timeout
        None,  # ALTER TABLE
        None,  # CREATE INDEX
    ]
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session

    with patch("core.database.AsyncSessionLocal", factory):
        await worker._ensure_archive_table_schema()

    alter = str(session.execute.await_args_list[4].args[0])
    assert 'ALTER TABLE "newsite"' in alter
    assert f"ADD COLUMN IF NOT EXISTS job_id UUID DEFAULT {ARCHIVE_JOB_ID_DEFAULT}" in alter
    session.commit.assert_awaited_once()


async def test_startup_skips_a_table_with_an_entry_column_that_is_not_an_archive():
    from unittest.mock import AsyncMock, MagicMock, patch

    import worker

    session = AsyncMock()
    session.execute.side_effect = [
        [("notes",)],
        None,  # advisory lock
        MagicMock(first=MagicMock(return_value=("r", ["entry", "body"]))),
    ]
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session

    with patch("core.database.AsyncSessionLocal", factory):
        await worker._ensure_archive_table_schema()

    assert not any("ALTER TABLE" in str(c.args[0]) for c in session.execute.await_args_list)
    session.commit.assert_awaited_once()
