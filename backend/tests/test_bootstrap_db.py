"""Regression tests for the database bootstrap step (issue #55).

A fresh `docker compose up -d` produced an empty database with a crash-looping
worker because schema creation relied solely on postgres `initdb.d` and nothing
ran migrations. `scripts.bootstrap_db` now owns an idempotent bootstrap; these
tests pin its branch selection so the three deployment states each take the
correct, non-destructive action.
"""

import importlib.util
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Base
from scripts import bootstrap_db

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
_INIT_SQL_PATH = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"


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
    def _run_main_with_state(self, has_alembic, has_core, guard=None):
        detect = AsyncMock(return_value=(has_alembic, has_core))
        apply_init = AsyncMock()
        stamp = MagicMock()
        upgrade = MagicMock()
        # bootstrap_db.main() imports assert_db_at_head from core.schema_guard at call
        # time, so patch it at the source module.
        guard = guard or AsyncMock()
        with (
            patch.object(bootstrap_db, "_detect_state", detect),
            patch.object(bootstrap_db, "_apply_init_sql", apply_init),
            patch.object(bootstrap_db, "_alembic_stamp_head", stamp),
            patch.object(bootstrap_db, "_alembic_upgrade_head", upgrade),
            patch("core.schema_guard.assert_db_at_head", guard),
        ):
            bootstrap_db.main()
        return apply_init, stamp, upgrade

    def test_main_raises_when_head_assertion_fails(self):
        # Post-bootstrap guard rejects a stale/behind schema -> main propagates it.
        failing_guard = AsyncMock(side_effect=RuntimeError("not at head"))
        with pytest.raises(RuntimeError):
            self._run_main_with_state(True, True, guard=failing_guard)

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


class TestConvergenceMigration0025:
    """0025 repairs databases that init.sql and the migration chain built differently (BE-T15).

    It runs against every existing database, most of which already have some or
    all of the objects, so each statement must be a no-op where its object exists.
    """

    _FILENAME = "0025_converge_bootstrap_schema_drift.py"

    def _statements(self) -> list[str]:
        return [" ".join(statement.split()) for statement in _capture_upgrade_sql(self._FILENAME)]

    def test_reapplies_every_migration_0008_statement(self):
        # Databases bootstrapped from an init.sql that lacked 0008 are stamped past
        # it, so alembic never runs 0008 for them; 0025 has to carry the same DDL.
        statements = self._statements()
        for expected in _capture_upgrade_sql("0008_pixiv_author_collections.py"):
            assert " ".join(expected.split()) in statements, expected

    def test_adds_the_objects_only_init_sql_declared_with_the_same_definition(self):
        statements = self._statements()
        init_sql = " ".join(_INIT_SQL_PATH.read_text(encoding="utf-8").split())
        for index in (
            "CREATE INDEX IF NOT EXISTS idx_read_progress_user ON read_progress (user_id, last_read_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_read_progress_gallery ON read_progress (gallery_id, last_read_at DESC)",
        ):
            assert index in statements
            assert index in init_sql
        role_check = "ALTER TABLE users ADD CONSTRAINT chk_users_role CHECK (role IN ('admin', 'member', 'viewer'));"
        assert role_check in init_sql
        assert any(role_check in statement for statement in statements)

    def test_every_statement_is_guarded_so_a_complete_schema_is_left_untouched(self):
        for statement in self._statements():
            upper = statement.upper()
            if upper.startswith("DO $$"):
                # One anonymous block is a single command; its DDL runs only when
                # the catalog says the object is missing or still divergent.
                assert upper.endswith("END $$;"), statement
                assert "PG_CONSTRAINT" in upper or "PG_ATTRIBUTE" in upper, statement
                assert " IF EXISTS (" in upper or " IF NOT EXISTS (" in upper, statement
            else:
                # asyncpg prepares each op.execute(), which rejects multiple commands.
                assert ";" not in statement, statement
                assert upper.startswith(("CREATE TABLE IF NOT EXISTS ", "CREATE INDEX IF NOT EXISTS ")) or (
                    upper.startswith("ALTER TABLE ") and " ADD COLUMN IF NOT EXISTS " in upper
                ), statement
            for unguardable in ("ADD CONSTRAINT", "RENAME CONSTRAINT", "SET NOT NULL", "UPDATE "):
                if unguardable in upper:
                    assert upper.startswith("DO $$"), statement

    def test_renames_generated_constraint_names_only_when_the_migration_name_is_absent(self):
        renames = [statement for statement in self._statements() if "RENAME CONSTRAINT" in statement]
        renamed = {}
        for statement in renames:
            table, old, new = re.search(r"ALTER TABLE (\w+) RENAME CONSTRAINT (\w+) TO (\w+)", statement).groups()
            renamed[new] = old
            # Renaming onto an existing name raises, and the old name is absent on
            # databases built by the migrations: both must be checked per table.
            assert f"conrelid = '{table}'::regclass AND conname = '{old}'" in statement, statement
            assert f"conrelid = '{table}'::regclass AND conname = '{new}'" in statement, statement
            assert "IF EXISTS (" in statement and ") AND NOT EXISTS (" in statement, statement
        assert renamed == {
            "fk_images_replaced_by_image_id": "images_replaced_by_image_id_fkey",
            "ck_workbench_operation_status": "workbench_operations_status_check",
            "ck_gallery_metadata_field_origin": "gallery_metadata_field_states_origin_check",
            "ck_gallery_metadata_change_origin": "gallery_metadata_changes_origin_check",
            "fk_blob_relationship_decision_user": "blob_relationships_decision_by_user_id_fkey",
        }

    def test_backfills_null_options_before_setting_not_null_and_skips_when_already_not_null(self):
        blocks = [statement for statement in self._statements() if "SET NOT NULL" in statement]
        columns = set()
        for statement in blocks:
            table, column = re.search(r"ALTER TABLE (\w+) ALTER COLUMN (\w+) SET NOT NULL", statement).groups()
            columns.add((table, column))
            assert f"attrelid = '{table}'::regclass AND attname = '{column}' AND NOT attnotnull" in statement
            backfill = f"UPDATE {table} SET {column} = '{{}}' WHERE {column} IS NULL;"
            assert backfill in statement, statement
            assert statement.index(backfill) < statement.index("SET NOT NULL"), statement
        assert columns == {("download_jobs", "options"), ("subscriptions", "download_options")}


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


_SQL_STRING_OR_COMMENT = re.compile(r"'(?:[^']|'')*'|--[^\n]*")
_NESTED_PARENS = re.compile(r"\([^()]*\)")
_CREATE_TABLE = re.compile(r"\bCREATE TABLE (?:IF NOT EXISTS )?(\w+) ?\(", re.IGNORECASE)
_ALTER_TABLE = re.compile(r"\bALTER TABLE (?:IF EXISTS )?(\w+) ([^;]*)", re.IGNORECASE)
_CREATE_INDEX = re.compile(r"\bCREATE (?:UNIQUE )?INDEX (?:IF NOT EXISTS )?(\w+) ON (\w+)", re.IGNORECASE)
_ADD_COLUMN = re.compile(r"\bADD COLUMN (?:IF NOT EXISTS )?(\w+)", re.IGNORECASE)
_NAMED_CONSTRAINT = re.compile(r"(?<!DROP )(?<!RENAME )\bCONSTRAINT (\w+)", re.IGNORECASE)
_RENAME_CONSTRAINT = re.compile(r"\bRENAME CONSTRAINT (\w+) TO (\w+)", re.IGNORECASE)
_DROP_TABLE = re.compile(r"\bDROP TABLE (?:IF EXISTS )?(\w+)", re.IGNORECASE)
_DROP_INDEX = re.compile(r"\bDROP INDEX (?:IF EXISTS )?(\w+)", re.IGNORECASE)
_DROP_FROM_TABLE = re.compile(r"\bDROP (?:COLUMN|CONSTRAINT) (?:IF EXISTS )?(\w+)", re.IGNORECASE)
_TABLE_CONSTRAINT_KEYWORDS = frozenset({"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "EXCLUDE", "LIKE"})


def _sql_code(sql: str) -> str:
    """Drop comments, blank string literals and collapse whitespace so regexes only see code."""
    code = _SQL_STRING_OR_COMMENT.sub(lambda m: "''" if m[0].startswith("'") else "", sql)
    return " ".join(code.split())


def _parenthesized(code: str, start: int) -> str:
    """Return the text between ``start`` and the parenthesis closing the one opened just before it."""
    depth = 1
    for end in range(start, len(code)):
        depth += (code[end] == "(") - (code[end] == ")")
        if depth == 0:
            return code[start:end]
    raise AssertionError("unbalanced parentheses in CREATE TABLE")


def _objects_by_table(sql: str) -> dict[str, set[str]]:
    """Map each table to the names of the columns, indexes and named constraints ``sql`` creates on it."""
    code = _sql_code(sql)
    tables: dict[str, set[str]] = {}
    for match in _CREATE_TABLE.finditer(code):
        body = _parenthesized(code, match.end())
        names = tables.setdefault(match[1], set())
        names.update(_NAMED_CONSTRAINT.findall(body))
        # Collapse nested parentheses so only the commas separating definitions remain.
        replaced = 1
        while replaced:
            body, replaced = _NESTED_PARENS.subn("", body)
        for definition in filter(None, map(str.strip, body.split(","))):
            first_word = definition.split()[0]
            if first_word.upper() not in _TABLE_CONSTRAINT_KEYWORDS:
                names.add(first_word)
    for match in _ALTER_TABLE.finditer(code):
        names = tables.setdefault(match[1], set())
        names.update(_ADD_COLUMN.findall(match[2]))
        names.update(_NAMED_CONSTRAINT.findall(match[2]))
        names.update(new for _old, new in _RENAME_CONSTRAINT.findall(match[2]))
    for index, table in _CREATE_INDEX.findall(code):
        tables.setdefault(table, set()).add(index)
    return tables


def _objects_left_by_migrations() -> dict[str, set[str]]:
    """Replay every upgrade() and return what the migration chain leaves on each table at head."""
    head: dict[str, set[str]] = {}
    # Zero-padded filename prefixes mirror the revision chain, so sorting gives upgrade order.
    for path in sorted(_VERSIONS_DIR.glob("[0-9]*.py")):
        for statement in _capture_upgrade_sql(path.name):
            code = _sql_code(statement)
            for table, names in _objects_by_table(code).items():
                head.setdefault(table, set()).update(names)
            for table in _DROP_TABLE.findall(code):
                head.pop(table, None)
            for table, clauses in _ALTER_TABLE.findall(code):
                head.get(table, set()).difference_update(_DROP_FROM_TABLE.findall(clauses))
                head.get(table, set()).difference_update(old for old, _new in _RENAME_CONSTRAINT.findall(clauses))
            for index in _DROP_INDEX.findall(code):
                for names in head.values():
                    names.discard(index)
    return head


class TestInitSqlMatchesHeadSchema:
    """db/init.sql must equal the HEAD schema (BE-T15).

    A fresh database is built from init.sql and stamped at head, so no migration
    ever runs against it and the revision guard still reports success: whatever a
    migration adds without mirroring it into init.sql is silently absent. Migration
    0008 did exactly that, leaving fresh deployments without gallery_source_items,
    images.source_item_row_id and read_progress.last_image_id.
    """

    def _init_sql_objects(self) -> dict[str, set[str]]:
        return _objects_by_table(_INIT_SQL_PATH.read_text(encoding="utf-8"))

    def test_init_sql_contains_every_orm_table_and_column(self):
        init_sql = self._init_sql_objects()
        missing = sorted(
            f"{table.name}.{column.name}"
            for table in Base.metadata.tables.values()
            for column in table.columns
            if column.name not in init_sql.get(table.name, ())
        )
        assert not missing, f"db/init.sql lacks columns the ORM loads: {missing}"

    def test_init_sql_contains_every_column_index_and_constraint_created_by_migrations(self):
        # The ORM does not declare most indexes and constraints, yet code depends on
        # them by name (e.g. ON CONFLICT ON CONSTRAINT uq_gallery_source_item).
        init_sql = self._init_sql_objects()
        missing = sorted(
            f"{table}.{name}"
            for table, names in _objects_left_by_migrations().items()
            for name in names - init_sql.get(table, set())
        )
        assert not missing, f"db/init.sql lacks objects that migrations create: {missing}"

    def test_init_sql_declares_download_option_columns_not_null(self):
        # Migration 0007 adds both columns as NOT NULL; a nullable copy in init.sql
        # gives fresh databases a looser contract than upgraded ones.
        code = _sql_code(_INIT_SQL_PATH.read_text(encoding="utf-8"))
        declarations = re.findall(r"\b(?:download_)?options JSONB [^,;)]*", code)
        assert declarations, "expected options / download_options column declarations"
        nullable = [declaration for declaration in declarations if "NOT NULL" not in declaration]
        assert not nullable, f"db/init.sql declares nullable option columns: {nullable}"


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
