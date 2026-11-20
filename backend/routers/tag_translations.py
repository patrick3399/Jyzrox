"""Tag translation endpoints."""

from fastapi import APIRouter, Depends, Query
from opencc import OpenCC
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.auth import require_auth, require_role
from core.database import async_session
from core.utils import escape_like
from db.models import TagTranslation
from services.tag_router_helpers import (
    translation_match as _translation_match,
)

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")
_s2twp = OpenCC("s2twp")


# ── Tag Translations ──────────────────────────────────────────────────


class TranslationUpsert(BaseModel):
    namespace: str
    name: str
    language: str = "zh"
    translation: str


class TranslationBatchImport(BaseModel):
    translations: list[TranslationUpsert]


@router.get("/translations")
async def get_translations(
    tags: str = Query(default="", description="Comma-separated 'namespace:name' list"),
    language: str = Query(default="zh"),
    _: dict = Depends(require_auth),
):
    """Batch look up translations for a list of tags."""
    if not tags:
        return {}

    tag_pairs = []
    for item in tags.split(","):
        item = item.strip()
        if ":" in item:
            ns, name = item.split(":", 1)
            tag_pairs.append((ns.strip(), name.strip()))

    if not tag_pairs:
        return {}

    db_language = "zh" if language == "zh-TW" else language

    async with async_session() as session:
        # Fetch all matching translations in one query
        from sqlalchemy import tuple_

        rows = (
            (
                await session.execute(
                    select(TagTranslation).where(
                        TagTranslation.language == db_language,
                        tuple_(TagTranslation.namespace, TagTranslation.name).in_(tag_pairs),
                    )
                )
            )
            .scalars()
            .all()
        )

    result = {}
    for r in rows:
        result[f"{r.namespace}:{r.name}"] = r.translation

    if language == "zh-TW":
        result = {k: _s2twp.convert(v) for k, v in result.items()}

    return result


@router.get("/translations/browse")
async def browse_translations(
    q: str | None = Query(default=None, description="Contains-search over name and translation"),
    namespace: str | None = Query(default=None, description="Exact namespace filter"),
    language: str = Query(default="zh"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: dict = Depends(require_auth),
):
    """
    Browse/search the full tag_translations table with pagination.

    Unlike GET /translations (batch lookup for a known tag list), this
    endpoint supports free-text search (name and translation) plus
    namespace/language filters over the entire table.
    """
    db_language = "zh" if language == "zh-TW" else language

    filters = [TagTranslation.language == db_language]
    if namespace:
        filters.append(TagTranslation.namespace == namespace)
    if q:
        safe_q = escape_like(q)
        filters.append(
            or_(
                TagTranslation.name.ilike(f"%{safe_q}%", escape="\\"),
                _translation_match(q, language),
            )
        )

    async with async_session() as session:
        count_query = select(func.count()).select_from(TagTranslation).where(*filters)
        total = (await session.execute(count_query)).scalar()

        data_query = (
            select(TagTranslation)
            .where(*filters)
            .order_by(TagTranslation.namespace, TagTranslation.name)
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(data_query)).scalars().all()

    items = [
        {
            "namespace": r.namespace,
            "name": r.name,
            "language": language,
            "translation": _s2twp.convert(r.translation) if language == "zh-TW" else r.translation,
        }
        for r in rows
    ]

    return {"total": total, "items": items}


@router.post("/translations")
async def upsert_translation(
    body: TranslationUpsert,
    _: dict = Depends(_admin),
):
    """Upsert a single tag translation."""
    async with async_session() as session:
        stmt = (
            pg_insert(TagTranslation)
            .values(
                namespace=body.namespace,
                name=body.name,
                language=body.language,
                translation=body.translation,
            )
            .on_conflict_do_update(
                index_elements=["namespace", "name", "language"],
                set_={"translation": body.translation},
            )
        )
        await session.execute(stmt)
        await session.commit()
    return {"status": "ok"}


@router.post("/translations/batch")
async def batch_import_translations(
    body: TranslationBatchImport,
    _: dict = Depends(_admin),
):
    """Bulk upsert tag translations."""
    if not body.translations:
        return {"status": "ok", "count": 0}

    async with async_session() as session:
        CHUNK = 1000
        items = body.translations
        for i in range(0, len(items), CHUNK):
            chunk = items[i : i + CHUNK]
            values = [
                {
                    "namespace": t.namespace,
                    "name": t.name,
                    "language": t.language,
                    "translation": t.translation,
                }
                for t in chunk
            ]
            stmt = (
                pg_insert(TagTranslation)
                .values(values)
                .on_conflict_do_update(
                    index_elements=["namespace", "name", "language"],
                    set_={"translation": pg_insert(TagTranslation).excluded.translation},
                )
            )
            await session.execute(stmt)
        await session.commit()
    return {"status": "ok", "count": len(body.translations)}
