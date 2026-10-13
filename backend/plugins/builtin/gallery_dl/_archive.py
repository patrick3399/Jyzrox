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
