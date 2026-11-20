"""Subscription create endpoint and its upsert statement builder."""

from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import gallery_access_filter, require_role
from core.database import async_session
from core.utils import detect_source, normalize_subscription_url, validate_cron
from db.models import DEFAULT_SUBSCRIPTION_CRON, Gallery, Subscription
from services.download_mode import find_account_subscription
from services.download_policy import normalize_download_options
from services.url_identity import account_gallery_key

router = APIRouter()

_member = require_role("member")


def _build_subscription_upsert(
    *,
    user_id: int,
    url: str,
    name: str | None,
    source: str | None,
    auto_download: bool,
    cron_expr: str,
    next_check,
    group_id: int | None,
    download_options: dict | None = None,
    source_id: str | None = None,
):
    """Build the create-or-upsert statement for a subscription.

    On conflict (same user_id+url, i.e. re-subscribing) the schedule fields are
    refreshed alongside cron_expr: ``next_check_at`` is recomputed from the new
    cron and ``source`` is re-synced from URL detection. Leaving next_check_at
    stale here would keep the old schedule active despite the updated cron
    (edge-case audit #10). ``group_id`` is intentionally NOT updated on conflict
    — group moves go through PATCH / bulk-move, so an upsert without an explicit
    group must not yank a subscription out of its existing group.
    """
    return (
        pg_insert(Subscription)
        .values(
            user_id=user_id,
            url=url,
            name=name,
            source=source,
            source_id=source_id,
            auto_download=auto_download,
            cron_expr=cron_expr,
            next_check_at=next_check,
            group_id=group_id,
            download_options=download_options or {},
        )
        .on_conflict_do_update(
            constraint="subscriptions_user_id_url_key",
            set_={
                "name": name,
                "source": source,
                "source_id": source_id,
                "auto_download": auto_download,
                "cron_expr": cron_expr,
                "next_check_at": next_check,
                "enabled": True,
                "download_options": download_options or {},
            },
        )
        .returning(Subscription.id)
    )


class CreateSubscriptionRequest(BaseModel):
    url: str
    name: str | None = None
    cron_expr: str | None = None
    # Opt-in: a new subscription only tracks new works until the user turns
    # auto-download on (per card, or via the create form).
    auto_download: bool = False
    group_id: int | None = None
    download_options: dict | None = None
    # Opt-in: answer 409 instead of overwriting the subscription this URL
    # already belongs to, so the caller can ask the user first.
    reject_duplicate: bool = False
    # Opt-in: answer 409 ``gallery_exists`` when this account URL already has a
    # gallery from an earlier download, so the caller can tell the user first.
    warn_existing_gallery: bool = False


async def _find_account_gallery(session, url: str, auth: dict) -> Gallery | None:
    """The visible, live gallery that ``url`` names as an account, if any."""
    key = account_gallery_key(url)
    if key is None:
        return None
    source, source_id = key
    return (
        await session.execute(
            select(Gallery)
            .where(
                Gallery.source == source,
                Gallery.source_id == source_id,
                Gallery.deleted_at.is_(None),
                Gallery.merged_into_gallery_id.is_(None),
                gallery_access_filter(auth),
            )
            .order_by(Gallery.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@router.post("/")
async def create_subscription(
    req: CreateSubscriptionRequest,
    auth: dict = Depends(_member),
):
    """Create a new subscription."""
    user_id = auth["user_id"]
    normalized_url = normalize_subscription_url(req.url)
    source: str | None = detect_source(normalized_url)
    if source == "unknown":
        source = None

    if req.cron_expr:
        validate_cron(req.cron_expr)

    cron_expr = req.cron_expr or DEFAULT_SUBSCRIPTION_CRON
    download_options = req.download_options or {}
    try:
        download_options = await normalize_download_options(normalized_url, source, download_options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid download options: {exc}") from exc
    next_check = croniter(cron_expr, datetime.now(UTC)).get_next(datetime)

    async with async_session() as session:
        existing = (
            await session.execute(
                select(Subscription.id, Subscription.name).where(
                    Subscription.user_id == user_id,
                    Subscription.url == normalized_url,
                )
            )
        ).one_or_none()

        if existing is not None and req.reject_duplicate:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "subscription_exists",
                    "subscription_id": existing.id,
                    "name": existing.name,
                    "url": normalized_url,
                },
            )

        # A different spelling of an account already subscribed to (www, http,
        # weibo.cn vs weibo.com) is the same subscription: both would fetch the
        # same account into the same gallery on every cycle. Refuse or reuse it
        # rather than creating a second row.
        account_key = account_gallery_key(normalized_url)
        if existing is None and account_key is not None:
            same_account = await find_account_subscription(session, user_id, source, account_key[1])
            if same_account is not None:
                if req.reject_duplicate:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "subscription_exists",
                            "subscription_id": same_account.id,
                            "name": same_account.name,
                            "url": same_account.url,
                        },
                    )
                return {"status": "ok", "id": same_account.id, "source": source, "duplicate": True}

        # A new subscription over an account that was downloaded before starts
        # from nothing (no boundary, no archive) and re-fetches what is already
        # held. Say so before creating it; the duplicate-subscription answer
        # above takes precedence because it is the more specific one.
        if existing is None and req.warn_existing_gallery:
            held = await _find_account_gallery(session, normalized_url, auth)
            if held is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "gallery_exists",
                        "url": normalized_url,
                        "gallery_id": held.id,
                        "source": held.source,
                        "source_id": held.source_id,
                        "title": held.title,
                        "pages": held.pages,
                        "download_status": held.download_status,
                    },
                )

        stmt = _build_subscription_upsert(
            user_id=user_id,
            url=normalized_url,
            name=req.name,
            source=source,
            auto_download=req.auto_download,
            cron_expr=cron_expr,
            next_check=next_check,
            group_id=req.group_id,
            download_options=download_options,
            source_id=account_key[1] if account_key else None,
        )

        result = await session.execute(stmt)
        row = result.fetchone()
        await session.commit()

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SUBSCRIPTION_CREATED,
        actor_user_id=auth["user_id"],
        resource_type="subscription",
        resource_id=row.id if row else None,
    )
    return {"status": "ok", "id": row.id if row else None, "source": source, "duplicate": existing is not None}
