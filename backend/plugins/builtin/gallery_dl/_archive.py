"""Ownership of gallery-dl archive rows.

gallery-dl writes an archive row as ``INSERT INTO "<category>" (entry)`` on its
own connection, so nothing in the row says which download produced it. Each
job therefore connects with its id as a session setting, and the ``job_id``
column default reads that setting: the row is stamped by the database at
insert time, and linking rows to a gallery never has to infer ownership from
timestamps.
"""

import uuid
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

ARCHIVE_JOB_SETTING = "jyzrox.archive_job_id"

# Column default for ``job_id`` on every archive table. NULL when the
# connection carries no job (a reset setting reads back as '').
ARCHIVE_JOB_ID_DEFAULT = f"NULLIF(current_setting('{ARCHIVE_JOB_SETTING}', true), '')::uuid"


def archive_dsn_for_job(dsn: str, job_id: str | None) -> str:
    """Return ``dsn`` with the job id passed to the server as a session setting.

    A missing or non-UUID job id leaves the DSN unchanged: its rows are then
    written without an owner rather than failing the cast on every insert.
    """
    if not job_id:
        return dsn
    try:
        job_uuid = uuid.UUID(str(job_id))
    except ValueError:
        return dsn

    parts = urlsplit(dsn)
    query = parse_qsl(parts.query, keep_blank_values=True)
    setting = f"-c {ARCHIVE_JOB_SETTING}={job_uuid}"
    for index, (key, value) in enumerate(query):
        if key == "options":
            query[index] = (key, f"{value} {setting}")
            break
    else:
        query.append(("options", setting))
    # libpq percent-decodes URI values but does not read "+" as a space.
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))


# Columns of an archive table: gallery-dl's ``entry`` plus what Jyzrox adds.
ARCHIVE_COLUMNS = frozenset({"entry", "gallery_id", "job_id", "created_at"})

# In the order a full table declares them (db/init.sql "gallery-dl archive tables").
_ADDED_COLUMN_DDL = (
    ("gallery_id", "gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE"),
    ("job_id", f"job_id UUID DEFAULT {ARCHIVE_JOB_ID_DEFAULT}"),
    ("created_at", "created_at TIMESTAMPTZ DEFAULT now()"),
)


class ArchiveTableConflict(Exception):
    """The archive table name for a category is taken by something that is not an archive."""


def archive_table_name(category: str) -> str:
    """Table gallery-dl's PostgreSQL archive uses for ``category``.

    ``"archive-table": "{category}"`` is passed through ``gallery_dl.archive.sanitize``,
    which replaces double quotes before quoting the name.
    """
    return category.replace('"', "_")


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def ensure_archive_table(session, category: str) -> str:
    """Give ``category``'s archive table the Jyzrox shape; returns what was done.

    gallery-dl only runs ``CREATE TABLE IF NOT EXISTS "<table>" (entry TEXT
    PRIMARY KEY)`` and only touches ``entry``, so a table created here first is
    used as is. Without ``gallery_id`` the rows of a new category are never
    linked: they survive the gallery's deletion and a re-download skips every
    file as already archived.

    - ``"created"``: no table yet; created with every column and the unlinked index.
    - ``"upgraded"``: a bare table gallery-dl made earlier; missing columns added.
    - ``"ok"``: already an archive table. Left alone, so the tables db/init.sql
      declares never drift from it and no table lock is taken.

    Raises ``ArchiveTableConflict`` when the name belongs to a relation that is
    not an archive table, e.g. an extractor whose category is ``galleries``.
    The caller commits.
    """
    from sqlalchemy import text

    table = archive_table_name(category)
    # Two downloads of a new category race on CREATE TABLE IF NOT EXISTS, which
    # can still fail on the pg_type unique index.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{ARCHIVE_JOB_SETTING}:{table}"},
    )
    row = (
        await session.execute(
            text(
                "SELECT c.relkind::text, array_remove(array_agg(a.attname::text), NULL) "
                "FROM pg_class c "
                "LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
                "WHERE c.relnamespace = CAST(current_schema() AS regnamespace) AND c.relname = :t "
                "GROUP BY c.relkind"
            ),
            {"t": table},
        )
    ).first()

    index = f"CREATE INDEX IF NOT EXISTS {_quoted(f'idx_{table}_unlinked')} ON {_quoted(table)} (job_id) WHERE gallery_id IS NULL"
    if row is None:
        columns = ",\n    ".join(["entry TEXT PRIMARY KEY", *(ddl for _, ddl in _ADDED_COLUMN_DDL)])
        await session.execute(text(f"CREATE TABLE {_quoted(table)} (\n    {columns}\n)"))
        await session.execute(text(index))
        return "created"

    relkind, columns = row[0], set(row[1] or ())
    if relkind not in ("r", "p") or "entry" not in columns:
        raise ArchiveTableConflict(
            f"gallery-dl category {category!r} would archive into {table!r}, which is not an archive table"
        )
    if {"gallery_id", "job_id"} <= columns:
        return "ok"
    if not columns <= ARCHIVE_COLUMNS:
        raise ArchiveTableConflict(
            f"gallery-dl category {category!r} would archive into {table!r}, "
            f"which has unexpected columns: {', '.join(sorted(columns - ARCHIVE_COLUMNS))}"
        )

    # ALTER TABLE waits for every running download of this category; give up
    # rather than stall the job behind a long transaction.
    await session.execute(text("SET LOCAL lock_timeout = '10s'"))
    adds = ", ".join(f"ADD COLUMN IF NOT EXISTS {ddl}" for name, ddl in _ADDED_COLUMN_DDL if name not in columns)
    await session.execute(text(f"ALTER TABLE {_quoted(table)} {adds}"))
    await session.execute(text(index))
    return "upgraded"
