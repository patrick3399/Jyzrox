"""Tag autocomplete endpoint."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, or_, select

from core.auth import require_auth, require_role
from core.database import async_session
from core.utils import escape_like
from db.models import Tag, TagTranslation
from services.tag_router_helpers import (
    translation_match as _translation_match,
)

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")


# ── Tag Autocomplete ──────────────────────────────────────────────────


@router.get("/autocomplete")
async def autocomplete_tags(
    q: str = Query(default="", description="Tag name prefix or 'namespace:name' prefix"),
    limit: int = Query(default=10, ge=1, le=30),
    language: str = Query(default="zh", description="Translation language for search and display"),
    _: dict = Depends(require_auth),
):
    """Return tags matching the given prefix (or translation), ordered by count DESC."""
    if not q:
        return []

    async with async_session() as session:
        base = select(
            Tag.id,
            Tag.namespace,
            Tag.name,
            Tag.count,
            TagTranslation.translation,
        ).outerjoin(
            TagTranslation,
            (TagTranslation.namespace == Tag.namespace)
            & (TagTranslation.name == Tag.name)
            & (TagTranslation.language == language),
        )

        if ":" in q:
            ns, name_prefix = q.split(":", 1)
            safe_ns = escape_like(ns)
            safe_name = escape_like(name_prefix)
            query = (
                base.where(
                    Tag.namespace.ilike(f"{safe_ns}%", escape="\\"),
                    or_(
                        Tag.name.ilike(f"{safe_name}%", escape="\\"),
                        _translation_match(name_prefix, language),
                    ),
                )
                .order_by(desc(Tag.count), desc(Tag.id))
                .limit(limit)
            )
        else:
            safe_q = escape_like(q)
            query = (
                base.where(
                    or_(
                        Tag.name.ilike(f"{safe_q}%", escape="\\"),
                        _translation_match(q, language),
                    )
                )
                .order_by(desc(Tag.count), desc(Tag.id))
                .limit(limit)
            )
        rows = (await session.execute(query)).all()

    return [
        {
            "id": r.id,
            "namespace": r.namespace,
            "name": r.name,
            "count": r.count,
            "translation": r.translation,
        }
        for r in rows
    ]
