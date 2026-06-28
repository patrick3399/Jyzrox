"""One-shot database bootstrap for fresh and existing deployments.

Run as ``python -m scripts.bootstrap_db`` (the compose ``migrate`` service).

This replaces the fragile postgres ``docker-entrypoint-initdb.d`` single-fire
mechanism: it owns schema creation and migration, is idempotent, and is safe to
run repeatedly and against existing deployments. See issue #55.

Decision logic (kept pure in :func:`choose_action` for unit testing):

* ``alembic_version`` table present  -> ``upgrade``       (run ``alembic upgrade head``)
* no version table, core schema present -> ``stamp``      (``alembic stamp head``)
* empty database                     -> ``init_then_stamp`` (apply ``db/init.sql``
  then ``alembic stamp head``)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Literal

logger = logging.getLogger("bootstrap_db")

Action = Literal["upgrade", "stamp", "init_then_stamp"]

# Path inside the migrate container; overridable for local runs / tests.
INIT_SQL_PATH = os.environ.get("INIT_SQL_PATH", "/app/db/init.sql")

# Bounded connect retry — depends_on already gates on postgres health, but a
# short retry keeps the migrate step robust against brief startup races.
_CONNECT_ATTEMPTS = 30
_CONNECT_DELAY_SECONDS = 2.0

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"


def choose_action(has_alembic_version: bool, has_core_schema: bool) -> Action:
    """Pick the bootstrap action from observed database state.

    Pure function so the branch logic can be unit-tested without a real DB.
    """
    if has_alembic_version:
        # Stamped database (existing deployment): apply any pending migrations.
        # For an already-current DB this is a no-op.
        return "upgrade"
    if has_core_schema:
        # Schema exists (e.g. created by init.sql) but was never stamped:
        # record the current revision without re-running DDL.
        return "stamp"
    # Empty database: create the schema from init.sql, then stamp.
    return "init_then_stamp"


async def _detect_state(dsn: str) -> tuple[bool, bool]:
    """Return (has_alembic_version, has_core_schema) for the target database."""
    import asyncpg

    last_error: Exception | None = None
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            conn = await asyncpg.connect(dsn)
            break
        except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - timing
            last_error = exc
            logger.info(
                "Waiting for database (attempt %s/%s): %s",
                attempt,
                _CONNECT_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(_CONNECT_DELAY_SECONDS)
    else:  # pragma: no cover - only on sustained outage
        raise RuntimeError(f"Could not connect to database after {_CONNECT_ATTEMPTS} attempts") from last_error

    try:
        has_alembic = (await conn.fetchval("SELECT to_regclass('public.alembic_version')")) is not None
        has_core = (await conn.fetchval("SELECT to_regclass('public.galleries')")) is not None
    finally:
        await conn.close()
    return has_alembic, has_core


async def _apply_init_sql(dsn: str, init_sql_path: str) -> None:
    """Execute db/init.sql against an empty database via the raw asyncpg connection."""
    import asyncpg

    sql = Path(init_sql_path).read_text(encoding="utf-8")
    conn = await asyncpg.connect(dsn)
    try:
        # asyncpg's simple-query protocol runs the whole multi-statement script.
        await conn.execute(sql)
    finally:
        await conn.close()


def _alembic_config():
    from alembic.config import Config

    return Config(str(_ALEMBIC_INI))


def _alembic_upgrade_head() -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def _alembic_stamp_head() -> None:
    from alembic import command

    command.stamp(_alembic_config(), "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from core.config import settings

    dsn = settings.gdl_archive_dsn  # asyncpg-compatible (postgresql://...) DSN

    has_alembic, has_core = asyncio.run(_detect_state(dsn))
    action = choose_action(has_alembic, has_core)
    logger.info(
        "Database state: alembic_version=%s core_schema=%s -> action=%s",
        has_alembic,
        has_core,
        action,
    )

    # Each asyncio.run() below completes before Alembic starts its own event loop
    # (env.py uses asyncio.run), so the two never nest.
    if action == "init_then_stamp":
        logger.info("Applying %s", INIT_SQL_PATH)
        asyncio.run(_apply_init_sql(dsn, INIT_SQL_PATH))
        _alembic_stamp_head()
    elif action == "stamp":
        _alembic_stamp_head()
    else:  # "upgrade"
        _alembic_upgrade_head()

    # Alembic's env.py runs logging.fileConfig(), which disables pre-existing
    # loggers (including ours), so print the final status to guarantee it is
    # visible in `docker compose logs migrate`.
    print(f"Bootstrap complete ({action}).", flush=True)


if __name__ == "__main__":
    main()
