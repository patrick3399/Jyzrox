"""Download job modes and the policy that follows from them.

Every download job carries one explicit mode, decided when the row is written
(routers/download.py::_enqueue, worker/subscription.py) and never at run time,
so a retry or startup recovery replays the same mode:

* ``download`` - a manual run. Full scan, gallery-dl archive trusted, owns no
  subscription boundary. Running it again continues what the archive lacks.
* ``subscription_initial`` - a subscription's first run (no boundary yet).
* ``subscription_incremental`` - a later run: ``date-after`` + ``abort:10``.
* ``repair`` - full scan against an empty shadow archive table, so files that
  are archived but missing locally are fetched again. Never moves a boundary.

Shared by routers and worker code; keep this module free of router imports.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import normalize_download_url
from db.models import DownloadJob, Subscription

DOWNLOAD = "download"
SUBSCRIPTION_INITIAL = "subscription_initial"
SUBSCRIPTION_INCREMENTAL = "subscription_incremental"
REPAIR = "repair"

MODES = frozenset({DOWNLOAD, SUBSCRIPTION_INITIAL, SUBSCRIPTION_INCREMENTAL, REPAIR})
SUBSCRIPTION_MODES = frozenset({SUBSCRIPTION_INITIAL, SUBSCRIPTION_INCREMENTAL})

# PostgreSQL truncates identifiers longer than this many bytes.
_PG_IDENTIFIER_MAX_BYTES = 63
_REPAIR_SUFFIX_MARKER = "__repair_"


def subscription_mode(*, has_boundary: bool, force_full_scan: bool) -> str:
    """Mode of a subscription check: a forced re-scan repairs, else boundary decides."""
    if force_full_scan:
        return REPAIR
    if has_boundary:
        return SUBSCRIPTION_INCREMENTAL
    return SUBSCRIPTION_INITIAL


def effective_mode(mode: str | None, options: dict | None) -> str:
    """Resolve the mode a job runs with, including rows from before the column existed.

    A stamped non-``download`` mode wins. ``download`` is also the column
    default, so a legacy row looks the same as a manual one; its options tell
    them apart (``force_full_scan`` -> repair, ``job_context == "subscription"``
    -> initial/incremental by ``last_completed_at``). An unknown value is a
    manual download.
    """
    if mode in MODES and mode != DOWNLOAD:
        return str(mode)
    if mode is not None and mode != DOWNLOAD:
        return DOWNLOAD

    opts = options if isinstance(options, dict) else {}
    if opts.get("force_full_scan"):
        return REPAIR
    if opts.get("job_context") == "subscription":
        return SUBSCRIPTION_INCREMENTAL if opts.get("last_completed_at") else SUBSCRIPTION_INITIAL
    return DOWNLOAD


def gallery_status_on_stop(mode: str) -> str:
    """Gallery ``download_status`` a stopped job leaves behind.

    A subscription stop means "caught up to the boundary the user chose", so the
    gallery is ``complete`` (``partial`` would offer repair/re-download actions
    that pull the dropped history back in). A manual or repair run stays
    resumable.
    """
    return "complete" if mode in SUBSCRIPTION_MODES else "partial"


def stop_discards(mode: str) -> bool:
    """Whether cancel throws the run away. Repaired files are wanted, so repair keeps (cancel = stop)."""
    return mode != REPAIR


def repair_archive_table(real_table: str, job_id: str) -> str:
    """Per-job shadow archive table name: ``<real>__repair_<jobhex>``.

    The result never exceeds PostgreSQL's 63-byte identifier limit; when the
    category name is too long only its leading part is kept (the job hex keeps
    the name unique).
    """
    suffix = f"{_REPAIR_SUFFIX_MARKER}{uuid.UUID(str(job_id)).hex}"
    room = _PG_IDENTIFIER_MAX_BYTES - len(suffix.encode())
    prefix = real_table.encode()[:room].decode(errors="ignore")
    return f"{prefix}{suffix}"


async def find_gallery_subscription(session: AsyncSession, gallery_id: int, user_id: int) -> Subscription | None:
    """The user's subscription that owns ``gallery_id`` as a whole, if any.

    A subscription owns a gallery only when the newest linking job fetched the
    subscription's own URL (whole-URL gallery-dl subscriptions, Pixiv author
    collections). A per-work gallery (e.g. one Fanbox post) also carries a
    ``subscription_id``, but its job URL is the post, not the creator: repairing
    it with the creator URL or running a creator check would not touch that post.
    """
    stmt = (
        select(DownloadJob.canonical_url, Subscription)
        .join(Subscription, DownloadJob.subscription_id == Subscription.id)
        .where(
            DownloadJob.gallery_id == gallery_id,
            DownloadJob.subscription_id.is_not(None),
            Subscription.user_id == user_id,
        )
        .order_by(DownloadJob.created_at.desc(), DownloadJob.id.desc())
    )
    for job_url, sub in (await session.execute(stmt)).all():
        try:
            if job_url and job_url == normalize_download_url(sub.url):
                return sub
        except ValueError:
            continue
    return None


async def find_subscription_for_url(session: AsyncSession, canonical_url: str, user_id: int) -> Subscription | None:
    """The user's subscription whose URL normalizes to ``canonical_url``, if any."""
    subs = (
        (await session.execute(select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id)))
        .scalars()
        .all()
    )
    for sub in subs:
        try:
            if normalize_download_url(sub.url) == canonical_url:
                return sub
        except ValueError:
            continue
    return None
