"""Tag listing endpoint."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select

from core.auth import require_auth, require_role
from core.database import async_session
from db.models import Tag
from services.tag_router_helpers import (
    decode_tag_cursor as _decode_tag_cursor,
)
from services.tag_router_helpers import (
    encode_tag_cursor as _encode_tag_cursor,
)

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")


# ── List tags ────────────────────────────────────────────────────────


@router.get("/")
async def list_tags(
    prefix: str | None = None,
    namespace: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None),
    _: dict = Depends(require_auth),
):
    """
    List tags sorted by count DESC.

    Supports cursor-based pagination (cursor=) for O(1) seek without COUNT(*)/OFFSET.
    Falls back to offset-based pagination when cursor is absent (max offset 10 000).
    """
    filters = []
    if prefix:
        safe_prefix = prefix.replace("%", "\\%").replace("_", "\\_")
        filters.append(Tag.name.like(f"{safe_prefix}%"))
    if namespace:
        filters.append(Tag.namespace == namespace)

    async with async_session() as session:
        if cursor is not None:
            # Keyset pagination on (count DESC, id DESC)
            c = _decode_tag_cursor(cursor)
            cursor_count = c["count"]
            cursor_id = c["id"]

            data_query = (
                select(Tag)
                .where(*filters)
                .where(
                    or_(
                        Tag.count < cursor_count,
                        (Tag.count == cursor_count) & (Tag.id < cursor_id),
                    )
                )
                .order_by(desc(Tag.count), desc(Tag.id))
                .limit(limit + 1)
            )
            rows = (await session.execute(data_query)).scalars().all()

            has_next = len(rows) > limit
            if has_next:
                rows = rows[:limit]

            next_cursor = _encode_tag_cursor(rows[-1]) if has_next and rows else None
            return {
                "tags": [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows],
                "next_cursor": next_cursor,
                "has_next": has_next,
            }

        else:
            # Legacy offset-based pagination — keep COUNT(*) for backward compat
            if offset > 10_000:
                raise HTTPException(status_code=400, detail="Offset too large. Use cursor= for deep pagination.")

            data_query = select(Tag).where(*filters).order_by(desc(Tag.count), desc(Tag.id)).limit(limit).offset(offset)
            rows = (await session.execute(data_query)).scalars().all()

            count_query = select(func.count()).select_from(Tag).where(*filters)
            total = (await session.execute(count_query)).scalar()

    return {
        "total": total,
        "tags": [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows],
    }
