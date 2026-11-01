"""Row builders shared by the download-modes / stop-and-keep tests (SQLite-backed)."""

import uuid
from datetime import UTC, datetime

from db.models import DownloadJob, Gallery, Subscription

EH_URL = "https://e-hentai.org/g/123/abcdef0123/"


async def add_job(session, **overrides) -> DownloadJob:
    url = overrides.pop("url", EH_URL)
    job = DownloadJob(
        id=overrides.pop("id", uuid.uuid4()),
        url=url,
        canonical_url=overrides.pop("canonical_url", url),
        source=overrides.pop("source", "ehentai"),
        status=overrides.pop("status", "queued"),
        progress=overrides.pop("progress", {}),
        options=overrides.pop("options", {}),
        user_id=overrides.pop("user_id", 1),
        mode=overrides.pop("mode", "download"),
        **overrides,
    )
    session.add(job)
    await session.commit()
    return job


async def add_subscription(session, **overrides) -> Subscription:
    sub = Subscription(
        user_id=overrides.pop("user_id", 1),
        url=overrides.pop("url", "https://x.com/someone"),
        name=overrides.pop("name", "Someone"),
        source=overrides.pop("source", "gallery_dl"),
        download_options=overrides.pop("download_options", {}),
        last_status=overrides.pop("last_status", "pending"),
        **overrides,
    )
    session.add(sub)
    await session.commit()
    return sub


async def add_gallery(session, **overrides) -> Gallery:
    gallery = Gallery(
        source=overrides.pop("source", "ehentai"),
        source_id=overrides.pop("source_id", "123"),
        title=overrides.pop("title", "A gallery"),
        source_url=overrides.pop("source_url", EH_URL),
        download_status=overrides.pop("download_status", "partial"),
        created_by_user_id=overrides.pop("created_by_user_id", 1),
        **overrides,
    )
    session.add(gallery)
    await session.commit()
    return gallery


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)
