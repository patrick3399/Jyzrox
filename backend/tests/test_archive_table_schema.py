"""Regression: every gallery-dl archive table must carry job_id.

Archive linking falls back to ``UPDATE ... SET job_id = :jid`` (strategy 2 in
ProgressiveImporter._link_archive_entries). A pre-created table without the
column makes that statement fail, so its entries are never linked to a gallery
and survive the gallery's deletion (instagram: 6017 unlinked rows, 2026-10-08).
"""

import importlib.util
import re
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_INIT_SQL = (_BACKEND_DIR.parent / "db" / "init.sql").read_text(encoding="utf-8")
_MIGRATION = _BACKEND_DIR / "migrations" / "versions" / "0028_archive_tables_job_id.py"

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", re.DOTALL)


def _archive_tables() -> dict[str, str]:
    return {
        name: body
        for name, body in _CREATE_TABLE_RE.findall(_INIT_SQL)
        if re.search(r"^\s*entry\s+TEXT PRIMARY KEY", body, re.M)
    }


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0028", _MIGRATION)
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
    assert set(_archive_tables()) <= set(module.ARCHIVE_TABLES) | {"exhentai", "pixiv", "twitter", "weibo"}

    executed: list[str] = []
    module.op = type("Op", (), {"execute": staticmethod(executed.append)})
    module.upgrade()

    for table in module.ARCHIVE_TABLES:
        statement = next(sql for sql in executed if f"ALTER TABLE {table} " in sql)
        assert "ADD COLUMN IF NOT EXISTS job_id UUID" in statement
        assert f"to_regclass('public.{table}') IS NOT NULL" in statement
