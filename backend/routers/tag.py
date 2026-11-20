"""Tag, Alias, and Implication management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, or_, select

from core.auth import require_role
from core.database import async_session
from db.models import GalleryTag, Tag, TagAlias, TagImplication
from routers import (
    tag_autocomplete,
    tag_blocked_manual,
    tag_health,
    tag_list,
    tag_relations,
    tag_translations,
)
from services.tag_router_helpers import (
    decode_tag_cursor as _decode_tag_cursor,
)
from services.tag_router_helpers import (
    encode_tag_cursor as _encode_tag_cursor,
)
from services.tag_router_helpers import (
    has_cycle as _has_cycle,
)

__all__ = ["router", "_decode_tag_cursor", "_encode_tag_cursor", "_has_cycle"]

router = APIRouter(tags=["tags"])

_admin = require_role("admin")
_member = require_role("member")

router.include_router(tag_list.router)
router.include_router(tag_relations.router)
router.include_router(tag_autocomplete.router)
router.include_router(tag_translations.router)
router.include_router(tag_blocked_manual.router)
router.include_router(tag_health.router)


# ── Tag deletion ─────────────────────────────────────────────────────
#
# Registered after all other /health, /aliases, /implications, etc. static
# routes. `tag_id: int` restricts the path param to digit-only segments, so
# this cannot shadow any of the fixed-name routes above, but keeping it last
# in the file avoids any ambiguity for future readers.


@router.delete("/{tag_id}")
async def delete_tag(tag_id: int, auth: dict = Depends(_admin)):
    """
    Delete a single tag (Tag Health "delete" action).

    Rejected with 409 if still referenced by gallery_tags —
    Health-tab deletions target count==0 orphan tags, not in-use ones.
    On success, also removes tag_aliases pointing at it and any
    tag_implications it participates in.
    """
    async with async_session() as session:
        tag = await session.get(Tag, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        gt_count = (
            await session.execute(select(func.count()).select_from(GalleryTag).where(GalleryTag.tag_id == tag_id))
        ).scalar()
        if gt_count:
            raise HTTPException(status_code=409, detail="Tag is still in use")

        await session.execute(delete(TagAlias).where(TagAlias.canonical_id == tag_id))
        await session.execute(
            delete(TagImplication).where(
                or_(TagImplication.antecedent_id == tag_id, TagImplication.consequent_id == tag_id)
            )
        )
        await session.delete(tag)
        await session.commit()

    from core.events import EventType, emit_safe

    await emit_safe(EventType.TAGS_UPDATED, actor_user_id=auth["user_id"], resource_type="tag", resource_id=tag_id)
    return {"status": "ok"}
