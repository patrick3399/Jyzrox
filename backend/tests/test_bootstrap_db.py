"""Regression tests for the database bootstrap step (issue #55).

A fresh `docker compose up -d` produced an empty database with a crash-looping
worker because schema creation relied solely on postgres `initdb.d` and nothing
ran migrations. `scripts.bootstrap_db` now owns an idempotent bootstrap; these
tests pin its branch selection so the three deployment states each take the
correct, non-destructive action.
"""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts import bootstrap_db

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"


def _load_migration(filename: str):
    """Load a digit-prefixed migration module by path (mirrors how alembic loads it)."""
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_upgrade_sql(filename: str) -> list[str]:
    """Run a migration's upgrade() with a mocked op and return emitted SQL strings."""
    module = _load_migration(filename)
    fake_op = MagicMock()
    module.op = fake_op  # type: ignore[attr-defined]
    module.upgrade()
    # All schema changes must go through op.execute (raw, guarded SQL).
    fake_op.add_column.assert_not_called()
    fake_op.create_index.assert_not_called()
    fake_op.create_foreign_key.assert_not_called()
    return [call.args[0] for call in fake_op.execute.call_args_list]


class TestChooseAction:
    def test_stamped_db_runs_upgrade_head(self):
        # Existing deployment with alembic_version present -> upgrade (no-op when current).
        assert bootstrap_db.choose_action(has_alembic_version=True, has_core_schema=True) == "upgrade"

    def test_unstamped_existing_schema_stamps_head_not_upgrade(self):
        # Schema exists (init.sql ran) but was never stamped: stamp, never re-run DDL.
        assert bootstrap_db.choose_action(has_alembic_version=False, has_core_schema=True) == "stamp"

    def test_empty_db_applies_init_sql_then_stamps_head(self):
        # The issue #55 case: nothing exists -> create schema then stamp.
        assert bootstrap_db.choose_action(has_alembic_version=False, has_core_schema=False) == "init_then_stamp"


class TestMainDispatch:
    def _run_main_with_state(self, has_alembic, has_core):
        detect = AsyncMock(return_value=(has_alembic, has_core))
        apply_init = AsyncMock()
        stamp = MagicMock()
        upgrade = MagicMock()
        with (
            patch.object(bootstrap_db, "_detect_state", detect),
            patch.object(bootstrap_db, "_apply_init_sql", apply_init),
            patch.object(bootstrap_db, "_alembic_stamp_head", stamp),
            patch.object(bootstrap_db, "_alembic_upgrade_head", upgrade),
        ):
            bootstrap_db.main()
        return apply_init, stamp, upgrade

    def test_empty_db_applies_init_sql_then_stamps_head(self):
        apply_init, stamp, upgrade = self._run_main_with_state(False, False)
        apply_init.assert_awaited_once()
        stamp.assert_called_once()
        upgrade.assert_not_called()

    def test_unstamped_existing_schema_stamps_without_running_init_or_upgrade(self):
        apply_init, stamp, upgrade = self._run_main_with_state(False, True)
        apply_init.assert_not_awaited()
        stamp.assert_called_once()
        upgrade.assert_not_called()

    def test_stamped_db_only_runs_upgrade_head(self):
        apply_init, stamp, upgrade = self._run_main_with_state(True, True)
        apply_init.assert_not_awaited()
        stamp.assert_not_called()
        upgrade.assert_called_once()


class TestMigrationIdempotency:
    """0002/0003 must be safe to run against an init.sql-built schema (issue #55)."""

    def test_0002_add_columns_are_guarded_with_if_not_exists(self):
        statements = _capture_upgrade_sql("0002_library_patterns_source_path.py")
        add_columns = [s for s in statements if "ADD COLUMN" in s]
        assert add_columns, "expected ADD COLUMN statements"
        for stmt in add_columns:
            assert "IF NOT EXISTS" in stmt, stmt

    def test_0003_columns_indexes_and_fk_are_all_idempotent(self):
        statements = _capture_upgrade_sql("0003_image_visibility_sync_state.py")
        for stmt in statements:
            if "ADD COLUMN" in stmt or "CREATE INDEX" in stmt:
                assert "IF NOT EXISTS" in stmt, stmt
        # The self-referential FK is guarded by a pg_constraint existence check.
        fk = [s for s in statements if "ADD CONSTRAINT" in s]
        assert fk and any("pg_constraint" in s for s in fk), fk


class TestInitSqlValidity:
    """db/init.sql must be valid, re-runnable PostgreSQL (bootstrap applies it whole)."""

    def _init_sql(self) -> str:
        path = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"
        return path.read_text(encoding="utf-8")

    def test_no_unsupported_add_constraint_if_not_exists(self):
        # PostgreSQL has no `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS`; it must
        # be guarded with a pg_constraint check instead (regression for the syntax
        # error surfaced applying init.sql on a fresh DB, issue #55).
        # Strip `--` line comments so explanatory text doesn't trip the check.
        code = "\n".join(line.split("--", 1)[0] for line in self._init_sql().splitlines()).upper()
        assert "ADD CONSTRAINT IF NOT EXISTS" not in code

    def test_role_constraint_present_and_guarded(self):
        sql = self._init_sql()
        assert "chk_users_role" in sql
        assert "pg_constraint" in sql  # guarded via existence check


@pytest.mark.asyncio
async def test_apply_init_sql_executes_full_script_via_raw_connection(tmp_path):
    """init.sql is run as a single multi-statement script through asyncpg."""
    init_file = tmp_path / "init.sql"
    init_file.write_text("CREATE TABLE a (id int);\nCREATE TABLE b (id int);\n")

    fake_conn = AsyncMock()
    with patch("asyncpg.connect", AsyncMock(return_value=fake_conn)):
        await bootstrap_db._apply_init_sql("postgresql://x/y", str(init_file))

    fake_conn.execute.assert_awaited_once()
    assert "CREATE TABLE a" in fake_conn.execute.await_args.args[0]
    fake_conn.close.assert_awaited_once()
