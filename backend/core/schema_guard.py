"""Schema-version guard shared by the migrate step and app startup.

The one domain rule lives in :func:`verify_at_head`: the database must be
stamped at the single alembic head declared by the running image's migration
scripts. ``bootstrap_db`` calls it after migrating; api and worker call
:func:`assert_db_at_head` at startup so a DB that a stale/mismatched migrate
step left behind head fails fast instead of serving on a stale schema.

Lives in ``core`` so both routers (api) and workers can import it without
crossing the worker→routers boundary (STAB-003).
"""

from __future__ import annotations

from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"


def _alembic_config():
    from alembic.config import Config

    return Config(str(_ALEMBIC_INI))


def alembic_heads() -> tuple[str, ...]:
    """Return the head revision id(s) declared by this image's migration scripts."""
    from alembic.script import ScriptDirectory

    return tuple(ScriptDirectory.from_config(_alembic_config()).get_heads())


async def current_db_revision(dsn: str) -> str | None:
    """Return the revision stamped in the DB's alembic_version table (or None)."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await conn.close()


def verify_at_head(current: str | None, heads: tuple[str, ...]) -> None:
    """Assert the DB is stamped at the one and only code head; raise otherwise.

    Pure function. Catches two failure modes that otherwise pass silently:

    * ``len(heads) != 1`` — a branched/ambiguous revision chain (e.g. a
      duplicate revision id creating two heads).
    * ``current not in heads`` — the DB did not reach head (partial/no-op
      upgrade, or a migrate image older than the app image).
    """
    if len(heads) != 1:
        raise RuntimeError(
            f"Expected exactly one alembic head, found {len(heads)}: {heads}. "
            "The revision chain is branched — refusing to report success."
        )
    if current not in heads:
        raise RuntimeError(
            f"Database revision {current!r} is not at head {heads[0]!r} — "
            "schema was not fully migrated (stale migrate image or failed upgrade?)."
        )


async def assert_db_at_head(dsn: str) -> None:
    """Fail fast unless the DB is stamped at this image's single alembic head."""
    verify_at_head(await current_db_revision(dsn), alembic_heads())
