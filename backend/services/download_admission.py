"""Durable FIFO admission for source-scoped downloads.

PostgreSQL is the authority for both ordering and ownership. SAQ delivery is
intentionally disposable: duplicate or delayed deliveries can only enter the
pipeline after atomically claiming a fenced token here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DownloadJob


@dataclass(frozen=True, slots=True)
class AdmissionClaim:
    acquired: bool
    token: uuid.UUID | None = None
    queue_position: int | None = None


def admission_key_for(source: str | None, url: str) -> str:
    """Return the durable capacity bucket for a persisted download request."""
    source_id = source or "gallery_dl"
    if source_id in {"ehentai", "pixiv", "fanbox"}:
        return source_id
    # detect_source() returns the concrete gallery-dl site (for example
    # "twitter" or "weibo"), while the fallback plugin deliberately scopes
    # capacity by hostname. Persist that final key before SAQ delivery so a
    # later transport attempt cannot enter ahead of an older row.
    domain = (urlparse(url).hostname or "unknown").removeprefix("www.")
    return f"gallery_dl:{domain}"


async def next_admission_ticket(session: AsyncSession) -> int:
    """Allocate a fresh FIFO ticket on PostgreSQL and in SQLite tests."""
    dialect_name = getattr(getattr(getattr(session, "bind", None), "dialect", None), "name", None)
    if dialect_name == "postgresql":
        return int((await session.execute(text("SELECT nextval('download_admission_ticket_seq')"))).scalar_one())
    if dialect_name == "sqlite":
        value = (await session.execute(select(func.max(DownloadJob.admission_ticket)))).scalar_one()
        return int(value or 0) + 1
    # Lightweight unit doubles do not expose a real bind. The value only has
    # to be fresh within that isolated call; real runtimes always use one of
    # the database branches above.
    import time

    return time.time_ns()


class DownloadAdmission:
    """Claim and release source capacity using a transaction-scoped lock."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def _is_postgres(self) -> bool:
        return bool(self.session.bind is not None and self.session.bind.dialect.name == "postgresql")

    async def _lock_key(self, key: str) -> None:
        if self._is_postgres:
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:admission_key, 0))"),
                {"admission_key": key},
            )

    async def claim(self, job_id: uuid.UUID | str, key: str, max_count: int) -> AdmissionClaim:
        """Atomically claim one of the first ``max_count`` FIFO positions."""
        job_uuid = uuid.UUID(str(job_id))
        await self._lock_key(key)

        stmt = select(DownloadJob).where(DownloadJob.id == job_uuid)
        if self._is_postgres:
            stmt = stmt.with_for_update()
        job = (await self.session.execute(stmt)).scalar_one_or_none()
        if job is None or job.status != "queued" or job.admission_token is not None:
            await self.session.rollback()
            return AdmissionClaim(acquired=False)

        job.admission_key = key
        if job.admission_ticket is None:
            job.admission_ticket = await next_admission_ticket(self.session)
        await self.session.flush()

        ordered_ids = list(
            (
                await self.session.execute(
                    select(DownloadJob.id)
                    .where(
                        DownloadJob.admission_key == key,
                        DownloadJob.status == "queued",
                        DownloadJob.admission_token.is_(None),
                    )
                    .order_by(DownloadJob.admission_ticket.asc(), DownloadJob.id.asc())
                )
            ).scalars()
        )
        try:
            queue_position = ordered_ids.index(job_uuid) + 1
        except ValueError:
            await self.session.rollback()
            return AdmissionClaim(acquired=False)

        holders = int(
            (
                await self.session.execute(
                    select(func.count())
                    .select_from(DownloadJob)
                    .where(
                        DownloadJob.admission_key == key,
                        DownloadJob.admission_token.is_not(None),
                    )
                )
            ).scalar_one()
        )
        available = max(0, max(1, int(max_count)) - holders)
        if queue_position > available:
            await self.session.commit()
            return AdmissionClaim(acquired=False, queue_position=queue_position)

        token = uuid.uuid4()
        result = await self.session.execute(
            update(DownloadJob)
            .where(
                DownloadJob.id == job_uuid,
                DownloadJob.status == "queued",
                DownloadJob.admission_token.is_(None),
            )
            .values(status="running", admission_key=key, admission_token=token)
        )
        if result.rowcount != 1:
            await self.session.rollback()
            return AdmissionClaim(acquired=False, queue_position=queue_position)
        await self.session.commit()
        return AdmissionClaim(acquired=True, token=token, queue_position=queue_position)

    async def release(self, job_id: uuid.UUID | str, token: uuid.UUID | str | None) -> bool:
        """Release only when the caller still owns the exact execution token."""
        if token is None:
            return False
        result = await self.session.execute(
            update(DownloadJob)
            .where(
                DownloadJob.id == uuid.UUID(str(job_id)),
                DownloadJob.admission_token == uuid.UUID(str(token)),
            )
            .values(admission_token=None)
        )
        await self.session.commit()
        return result.rowcount == 1

    async def token_is_valid(self, job_id: uuid.UUID | str, token: uuid.UUID | str) -> bool:
        """Check the fence used by a long-running child process heartbeat."""
        current = (
            await self.session.execute(
                select(DownloadJob.admission_token).where(DownloadJob.id == uuid.UUID(str(job_id)))
            )
        ).scalar_one_or_none()
        await self.session.rollback()
        return current is not None and str(current) == str(token)

    async def recover_stale_tokens(self) -> int:
        """Clear process-owned tokens left behind by a previous worker."""
        result = await self.session.execute(
            update(DownloadJob).where(DownloadJob.admission_token.is_not(None)).values(admission_token=None)
        )
        await self.session.commit()
        return int(result.rowcount or 0)
