"""Tag, Alias, and Implication management endpoints."""

import base64
import json
import re
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from opencc import OpenCC
from pydantic import BaseModel
from sqlalchemy import case as sql_case
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy import literal as sql_literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import core.queue
from core.auth import gallery_access_filter, has_gallery_write_access, require_auth, require_role
from core.database import async_session, get_db
from core.redis_client import get_redis
from core.utils import escape_like
from db.models import BlockedTag, Gallery, GalleryTag, Image, ImageTag, Tag, TagAlias, TagImplication, TagTranslation
from services.settings_store import get_toggle

_s2twp = OpenCC("s2twp")
_t2s = OpenCC("t2s")

router = APIRouter(tags=["tags"])

_admin = require_role("admin")
_member = require_role("member")


# ── Cursor helpers ────────────────────────────────────────────────────


def _encode_tag_cursor(tag: Tag) -> str:
    payload = {"id": tag.id, "count": tag.count}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_tag_cursor(cursor: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor + "=="))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


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


# ── Aliases ──────────────────────────────────────────────────────────


class AliasRequest(BaseModel):
    alias_namespace: str
    alias_name: str
    canonical_id: int


@router.get("/aliases")
async def list_aliases(
    tag_id: int | None = None,
    limit: int = 50,
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        query = (
            select(
                TagAlias.alias_namespace,
                TagAlias.alias_name,
                TagAlias.canonical_id,
                Tag.namespace.label("canonical_namespace"),
                Tag.name.label("canonical_name"),
            )
            .join(Tag, TagAlias.canonical_id == Tag.id)
            .order_by(TagAlias.alias_name)
            .limit(limit)
        )
        if tag_id:
            query = query.where(TagAlias.canonical_id == tag_id)

        rows = (await session.execute(query)).all()

    return [
        {
            "alias_namespace": r.alias_namespace,
            "alias_name": r.alias_name,
            "canonical_id": r.canonical_id,
            "canonical_namespace": r.canonical_namespace,
            "canonical_name": r.canonical_name,
        }
        for r in rows
    ]


@router.post("/aliases")
async def create_alias(req: AliasRequest, _: dict = Depends(_admin)):
    async with async_session() as session:
        tag = (await session.execute(select(Tag.id).where(Tag.id == req.canonical_id))).fetchone()
        if not tag:
            raise HTTPException(status_code=404, detail="Canonical tag not found")

        # Normalize to lowercase so aliases are case-insensitive — edge case #127.
        ns = req.alias_namespace.lower()
        name = req.alias_name.lower()

        # Upsert alias
        existing = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == ns,
                    TagAlias.alias_name == name,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.canonical_id = req.canonical_id
        else:
            session.add(
                TagAlias(
                    alias_namespace=ns,
                    alias_name=name,
                    canonical_id=req.canonical_id,
                )
            )
        await session.commit()
    return {"status": "ok"}


@router.delete("/aliases")
async def delete_alias(
    alias_namespace: str = Query(...),
    alias_name: str = Query(...),
    _: dict = Depends(_admin),
):
    async with async_session() as session:
        alias = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == alias_namespace.lower(),
                    TagAlias.alias_name == alias_name.lower(),
                )
            )
        ).scalar_one_or_none()
        if alias:
            await session.delete(alias)
            await session.commit()
    return {"status": "ok"}


# ── Implications ─────────────────────────────────────────────────────


class ImplicationRequest(BaseModel):
    antecedent_id: int
    consequent_id: int


@router.get("/implications")
async def list_implications(
    tag_id: int | None = None,
    limit: int = 50,
    _: dict = Depends(require_auth),
):
    ant = Tag.__table__.alias("ant")
    con = Tag.__table__.alias("con")

    async with async_session() as session:
        query = (
            select(
                TagImplication.antecedent_id,
                TagImplication.consequent_id,
                ant.c.namespace.label("ant_ns"),
                ant.c.name.label("ant_name"),
                con.c.namespace.label("con_ns"),
                con.c.name.label("con_name"),
            )
            .join(ant, TagImplication.antecedent_id == ant.c.id)
            .join(con, TagImplication.consequent_id == con.c.id)
            .order_by(ant.c.name)
            .limit(limit)
        )
        if tag_id:
            query = query.where(
                or_(
                    TagImplication.antecedent_id == tag_id,
                    TagImplication.consequent_id == tag_id,
                )
            )

        rows = (await session.execute(query)).all()

    return [
        {
            "antecedent_id": r.antecedent_id,
            "consequent_id": r.consequent_id,
            "antecedent": f"{r.ant_ns}:{r.ant_name}",
            "consequent": f"{r.con_ns}:{r.con_name}",
        }
        for r in rows
    ]


async def _has_cycle(session, from_id: int, target_id: int, max_depth: int = 50) -> bool:
    """
    BFS from `from_id` along existing implications.
    Returns True if `target_id` is reachable (i.e. adding target→from would create a cycle).
    Caps traversal at max_depth visited nodes; conservatively returns True if the limit is hit.
    """
    visited: set[int] = set()
    queue: deque[int] = deque([from_id])
    while queue and len(visited) < max_depth:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if current == target_id:
            return True
        rows = (
            (await session.execute(select(TagImplication.consequent_id).where(TagImplication.antecedent_id == current)))
            .scalars()
            .all()
        )
        queue.extend(r for r in rows if r not in visited)
    # If we hit the limit, conservatively assume a cycle exists
    return len(visited) >= max_depth


@router.post("/implications")
async def create_implication(req: ImplicationRequest, _: dict = Depends(_admin)):
    if req.antecedent_id == req.consequent_id:
        raise HTTPException(status_code=400, detail="Cannot imply self")
    async with async_session() as session:
        # Check for circular implication via BFS (detects chains of any length)
        if await _has_cycle(session, req.consequent_id, req.antecedent_id):
            raise HTTPException(status_code=400, detail="Circular implication detected")

        # Check if already exists
        existing = (
            await session.execute(
                select(TagImplication).where(
                    TagImplication.antecedent_id == req.antecedent_id,
                    TagImplication.consequent_id == req.consequent_id,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            session.add(
                TagImplication(
                    antecedent_id=req.antecedent_id,
                    consequent_id=req.consequent_id,
                )
            )
            await session.commit()
    return {"status": "ok"}


@router.delete("/implications")
async def delete_implication(
    antecedent_id: int = Query(...),
    consequent_id: int = Query(...),
    _: dict = Depends(_admin),
):
    async with async_session() as session:
        impl = (
            await session.execute(
                select(TagImplication).where(
                    TagImplication.antecedent_id == antecedent_id,
                    TagImplication.consequent_id == consequent_id,
                )
            )
        ).scalar_one_or_none()
        if impl:
            await session.delete(impl)
            await session.commit()
    return {"status": "ok"}


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
                        TagTranslation.translation.ilike(f"%{safe_name}%", escape="\\"),
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
                        TagTranslation.translation.ilike(f"%{safe_q}%", escape="\\"),
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
        q_filters = [
            TagTranslation.name.ilike(f"%{safe_q}%", escape="\\"),
            TagTranslation.translation.ilike(f"%{safe_q}%", escape="\\"),
        ]
        if language == "zh-TW":
            # DB stores simplified Chinese — also match a t2s-converted q
            # against translation so traditional-input searches still hit.
            safe_q_simplified = escape_like(_t2s.convert(q))
            q_filters.append(TagTranslation.translation.ilike(f"%{safe_q_simplified}%", escape="\\"))
        filters.append(or_(*q_filters))

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


# ── Blocked Tags ──────────────────────────────────────────────────────


class BlockedTagCreate(BaseModel):
    namespace: str
    name: str


@router.get("/blocked")
async def list_blocked_tags(
    auth: dict = Depends(require_auth),
):
    """List blocked tags for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        rows = (await session.execute(select(BlockedTag).where(BlockedTag.user_id == user_id))).scalars().all()
    return [{"id": r.id, "namespace": r.namespace, "name": r.name} for r in rows]


@router.post("/blocked", status_code=201)
async def add_blocked_tag(
    body: BlockedTagCreate,
    auth: dict = Depends(require_auth),
):
    """Add a blocked tag for the current user."""
    user_id = auth["user_id"]
    async with async_session() as session:
        # Use upsert to handle duplicate gracefully
        stmt = (
            pg_insert(BlockedTag)
            .values(user_id=user_id, namespace=body.namespace, name=body.name)
            .on_conflict_do_nothing(index_elements=["user_id", "namespace", "name"])
            .returning(BlockedTag.id)
        )
        result = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()
    return {"status": "ok", "id": result}


@router.delete("/blocked/{blocked_id}")
async def remove_blocked_tag(
    blocked_id: int,
    auth: dict = Depends(require_auth),
):
    """Remove a blocked tag."""
    user_id = auth["user_id"]
    async with async_session() as session:
        row = (
            await session.execute(
                select(BlockedTag).where(
                    BlockedTag.id == blocked_id,
                    BlockedTag.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Blocked tag not found")
        await session.delete(row)
        await session.commit()
    return {"status": "ok"}


# ── Manual Tagging ────────────────────────────────────────────────────


class ManualTagRequest(BaseModel):
    tags: list[str]  # "namespace:name" or bare "name"
    action: Literal["add", "remove"] = "add"


@router.post("/gallery/{gallery_id}")
async def manual_tag_gallery(
    gallery_id: int,
    body: ManualTagRequest,
    auth: dict = Depends(_member),
    session: AsyncSession = Depends(get_db),
):
    """Add or remove manual tags on a gallery."""
    from services.tag_helpers import rebuild_gallery_tags_array

    # Verify gallery exists and the caller may modify it. Read visibility is not
    # sufficient: gallery_access_filter matches read-only collaborators, so the
    # write must be gated on has_gallery_write_access (admin/owner/can_edit).
    gallery = await session.get(Gallery, gallery_id)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    if not await has_gallery_write_access(session, gallery.id, gallery.created_by_user_id, auth):
        raise HTTPException(status_code=403, detail="Gallery write access is required")

    if body.action == "add":
        from services.tag_helpers import parse_tag_strings

        parsed = parse_tag_strings(body.tags)

        if not parsed:
            return {"status": "ok", "affected": 0}

        # Upsert tags table (increment count)
        tag_values = [{"namespace": ns, "name": name, "count": 1} for ns, name in parsed]
        tag_stmt = (
            pg_insert(Tag)
            .values(tag_values)
            .on_conflict_do_update(
                index_elements=["namespace", "name"],
                set_={"count": Tag.count + 1},
            )
            .returning(Tag.id)
        )
        tag_ids = (await session.execute(tag_stmt)).scalars().all()

        # Upsert gallery_tags with source='manual'
        # ON CONFLICT: overwrite 'ai' source but not 'metadata'
        gt_values = [
            {"gallery_id": gallery_id, "tag_id": tid, "confidence": 1.0, "source": "manual"} for tid in tag_ids
        ]
        if gt_values:
            gt_stmt = (
                pg_insert(GalleryTag)
                .values(gt_values)
                .on_conflict_do_update(
                    index_elements=["gallery_id", "tag_id"],
                    set_={
                        "confidence": sql_case(
                            (GalleryTag.source == "metadata", GalleryTag.confidence),
                            else_=pg_insert(GalleryTag).excluded.confidence,
                        ),
                        "source": sql_case(
                            (GalleryTag.source == "metadata", GalleryTag.source),
                            else_=sql_literal("manual"),
                        ),
                    },
                )
            )
            await session.execute(gt_stmt)

        await rebuild_gallery_tags_array(session, gallery_id)
        await session.commit()
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.TAGS_UPDATED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=gallery_id
        )
        return {"status": "ok", "affected": len(tag_ids)}

    else:  # remove
        from services.tag_helpers import parse_tag_strings

        parsed = parse_tag_strings(body.tags)

        if not parsed:
            await rebuild_gallery_tags_array(session, gallery_id)
            await session.commit()
            return {"status": "ok", "affected": 0}

        # Query 1: resolve all (namespace, name) pairs to tag IDs in one round-trip
        ns_name_filter = or_(*[(Tag.namespace == ns) & (Tag.name == name) for ns, name in parsed])
        tag_ids = (await session.execute(select(Tag.id).where(ns_name_filter))).scalars().all()

        if not tag_ids:
            await rebuild_gallery_tags_array(session, gallery_id)
            await session.commit()
            return {"status": "ok", "affected": 0}

        # Query 2: find which tag_ids actually have manual source rows for this gallery
        manual_tag_ids = (
            (
                await session.execute(
                    select(GalleryTag.tag_id).where(
                        GalleryTag.gallery_id == gallery_id,
                        GalleryTag.tag_id.in_(tag_ids),
                        GalleryTag.source == "manual",
                    )
                )
            )
            .scalars()
            .all()
        )

        if not manual_tag_ids:
            await rebuild_gallery_tags_array(session, gallery_id)
            await session.commit()
            return {"status": "ok", "affected": 0}

        # Query 3: delete only the confirmed manual gallery_tags
        del_result = await session.execute(
            delete(GalleryTag).where(
                GalleryTag.gallery_id == gallery_id,
                GalleryTag.tag_id.in_(manual_tag_ids),
                GalleryTag.source == "manual",
            )
        )
        removed = del_result.rowcount

        # Decrement tag counts only for the tags that were actually deleted
        if removed > 0:
            await session.execute(
                Tag.__table__.update()
                .where(Tag.id.in_(manual_tag_ids))
                .values(
                    count=sql_case(
                        (Tag.count > 0, Tag.count - 1),
                        else_=0,
                    )
                )
            )

        await rebuild_gallery_tags_array(session, gallery_id)
        await session.commit()
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.TAGS_UPDATED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=gallery_id
        )
        return {"status": "ok", "affected": removed}


# ── AI Re-tag ─────────────────────────────────────────────────────────


@router.post("/retag/{gallery_id}")
async def retag_gallery(
    gallery_id: int,
    request: Request,
    _: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue AI tagging job for all images in a gallery."""
    from core.config import settings as app_settings

    if not await get_toggle("setting:ai_tagging_enabled", app_settings.tag_model_enabled):
        raise HTTPException(status_code=400, detail="AI tagging is not enabled")

    # Verify gallery exists
    gallery = await db.get(Gallery, gallery_id)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")
    await core.queue.enqueue("tag_job", gallery_id=gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}


@router.post("/clear-ai/{gallery_id}")
async def clear_gallery_ai_tags(
    gallery_id: int,
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Remove all AI-derived tags from a gallery, keeping manual/metadata tags (AIT-006)."""
    from services.tag_helpers import clear_ai_tags, rebuild_gallery_tags_array

    gallery = await db.get(Gallery, gallery_id)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    removed = await clear_ai_tags(db, gallery_id)
    await rebuild_gallery_tags_array(db, gallery_id)
    await db.commit()

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.TAGS_UPDATED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=gallery_id
    )
    return {"status": "ok", "removed": removed}


@router.post("/retag-all")
async def retag_all_galleries(
    request: Request,
    _: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue AI tagging jobs for ALL galleries (batch re-tag).

    Uses chunked queries and Redis pipeline to avoid loading all IDs
    into memory and doing 100K individual roundtrips.
    """
    from core.config import settings as app_settings

    if not await get_toggle("setting:ai_tagging_enabled", app_settings.tag_model_enabled):
        raise HTTPException(status_code=400, detail="AI tagging is not enabled")
    enqueued = 0
    CHUNK = 1000
    offset = 0

    while True:
        chunk = (await db.execute(select(Gallery.id).order_by(Gallery.id).offset(offset).limit(CHUNK))).scalars().all()

        if not chunk:
            break

        for gid in chunk:
            await core.queue.enqueue("tag_job", gallery_id=gid)
            enqueued += 1

        offset += CHUNK

    return {"status": "enqueued", "total": enqueued}


# ── EhTagTranslation Import ──────────────────────────────────────────


@router.post("/import-ehtag")
async def import_ehtag_translations(_: dict = Depends(_admin)):
    """Import ~50k Chinese translations from EhTagTranslation CDN."""
    from services.ehtag_importer import import_ehtag_translations as do_import

    try:
        count = await do_import()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch EhTag data: {exc}")
    return {"status": "ok", "count": count}


# ── Tag Health Report ──────────────────────────────────────────────────
#
# Detects orphan tags (count==0, not structural), suspected duplicates
# (normalized-name collisions within a namespace), and circular
# implications. See docs/superpowers/specs/2026-07-12-tag-health-report-design.md.

_TAG_HEALTH_IGNORE_REDIS_KEY = "setting:tag_health_ignored"

# Accepted ignore-key formats:
#   orphan:{tag_id}
#   dup:{namespace}:{normalized_name}   (normalized_name may be empty)
#   cycle:{id}(-{id})*
_TAG_HEALTH_IGNORE_KEY_RE = re.compile(r"^(orphan:\d+|dup:[^:]+:[^:]*|cycle:\d+(?:-\d+)*)$")


def _normalize_tag_name_key(namespace: str, normalized_name: str) -> str:
    return f"{namespace}:{normalized_name}"


def _find_implication_cycles(edges: list[tuple[int, int]]) -> list[list[int]]:
    """
    DFS-based cycle detection over the tag_implications graph.

    Returns a list of cycles, each represented as a list of tag ids in
    cyclic edge order, rotated so the smallest id comes first. Each
    distinct cycle (identified by its sorted-id key) is returned once.
    Self-loops (a -> a) are detected as single-node cycles.
    """
    adjacency: dict[int, list[int]] = {}
    for antecedent_id, consequent_id in edges:
        adjacency.setdefault(antecedent_id, []).append(consequent_id)

    visited: set[int] = set()
    seen_keys: set[str] = set()
    cycles: list[list[int]] = []

    def dfs(node: int, stack: list[int], on_stack: set[int]) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor in on_stack:
                idx = stack.index(neighbor)
                cycle = stack[idx:]
                key = "-".join(str(n) for n in sorted(cycle))
                if key not in seen_keys:
                    seen_keys.add(key)
                    min_idx = cycle.index(min(cycle))
                    cycles.append(cycle[min_idx:] + cycle[:min_idx])
            elif neighbor not in visited:
                dfs(neighbor, stack, on_stack)
        stack.pop()
        on_stack.discard(node)

    for start in list(adjacency):
        if start not in visited:
            dfs(start, [], set())

    return cycles


async def _get_tag_health_ignored_keys() -> set[str]:
    """Read the tag-health ignore set from Redis, decoding bytes to str."""
    raw = await get_redis().smembers(_TAG_HEALTH_IGNORE_REDIS_KEY)
    keys: set[str] = set()
    for item in raw or set():
        keys.add(item.decode() if isinstance(item, (bytes, bytearray)) else str(item))
    return keys


@router.get("/health")
async def get_tag_health(
    limit: int = Query(default=200, ge=1, le=2000),
    _: dict = Depends(_admin),
):
    """
    Report orphan tags, suspected duplicate groups, and circular
    implications, filtered against the persisted ignore list.

    `limit` only caps the returned `orphans` list; `orphans_total` reflects
    the full (post-ignore) count. Duplicates and cycles are returned in full
    since they are expected to be small in practice.
    """
    from sqlalchemy import exists as sql_exists

    ignored = await _get_tag_health_ignored_keys()
    ignored_count = 0

    async with async_session() as session:
        # ---- Orphans: count==0, not an alias target, not part of any implication ----
        orphan_stmt = (
            select(Tag.id, Tag.namespace, Tag.name, Tag.count)
            .where(
                Tag.count == 0,
                ~sql_exists().where(TagAlias.canonical_id == Tag.id),
                ~sql_exists().where(
                    or_(TagImplication.antecedent_id == Tag.id, TagImplication.consequent_id == Tag.id)
                ),
            )
            .order_by(Tag.namespace, Tag.name)
        )
        orphan_rows = (await session.execute(orphan_stmt)).all()

        orphans_kept = []
        for r in orphan_rows:
            if f"orphan:{r.id}" in ignored:
                ignored_count += 1
            else:
                orphans_kept.append({"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count})
        orphans_total = len(orphans_kept)
        orphans = orphans_kept[:limit]

        # ---- Duplicates: same namespace + normalized name, portable across pg/sqlite ----
        normalized_expr = func.replace(func.replace(func.replace(func.lower(Tag.name), "_", ""), "-", ""), " ", "")
        dup_stmt = select(Tag.id, Tag.namespace, Tag.name, Tag.count, normalized_expr.label("norm"))
        dup_rows = (await session.execute(dup_stmt)).all()

        groups: dict[tuple[str, str], list[dict]] = {}
        for r in dup_rows:
            groups.setdefault((r.namespace, r.norm), []).append(
                {"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count}
            )

        duplicates = []
        for (namespace, norm), tags in groups.items():
            if len(tags) < 2:
                continue
            group_key = _normalize_tag_name_key(namespace, norm)
            if f"dup:{group_key}" in ignored:
                ignored_count += 1
                continue
            duplicates.append({"key": group_key, "tags": sorted(tags, key=lambda t: t["count"], reverse=True)})

        # ---- Implication cycles ----
        edge_rows = (await session.execute(select(TagImplication.antecedent_id, TagImplication.consequent_id))).all()
        raw_cycles = _find_implication_cycles([(r[0], r[1]) for r in edge_rows])

        implication_cycles = []
        if raw_cycles:
            node_ids = {n for cyc in raw_cycles for n in cyc}
            tag_rows = (await session.execute(select(Tag).where(Tag.id.in_(node_ids)))).scalars().all()
            tag_map = {t.id: t for t in tag_rows}
            for cyc in raw_cycles:
                cycle_key = "-".join(str(n) for n in sorted(cyc))
                if f"cycle:{cycle_key}" in ignored:
                    ignored_count += 1
                    continue
                path = [
                    {"id": n, "namespace": tag_map[n].namespace, "name": tag_map[n].name} for n in cyc if n in tag_map
                ]
                implication_cycles.append({"key": cycle_key, "path": path})

    return {
        "orphans": orphans,
        "orphans_total": orphans_total,
        "duplicates": duplicates,
        "implication_cycles": implication_cycles,
        "ignored_count": ignored_count,
    }


class TagHealthIgnoreRequest(BaseModel):
    key: str


@router.post("/health/ignore")
async def ignore_tag_health_item(body: TagHealthIgnoreRequest, _: dict = Depends(_admin)):
    """Add an orphan/duplicate/cycle key to the persisted ignore set."""
    if not _TAG_HEALTH_IGNORE_KEY_RE.match(body.key):
        raise HTTPException(status_code=400, detail="Invalid ignore key format")
    await get_redis().sadd(_TAG_HEALTH_IGNORE_REDIS_KEY, body.key)
    return {"status": "ok"}


@router.delete("/health/ignore")
async def unignore_tag_health_item(key: str = Query(...), _: dict = Depends(_admin)):
    """Remove a key from the tag-health ignore set."""
    await get_redis().srem(_TAG_HEALTH_IGNORE_REDIS_KEY, key)
    return {"status": "ok"}


@router.get("/health/ignored")
async def list_tag_health_ignored(_: dict = Depends(_admin)):
    """List currently ignored tag-health keys (for the UI's ignored/restore view)."""
    keys = await _get_tag_health_ignored_keys()
    return {"keys": sorted(keys)}


@router.get("/anomalies")
async def get_tag_anomalies(
    min_difference: float = Query(default=0.6, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=500),
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Compare image-level AI confidence with gallery metadata tag confidence."""
    metadata_rows = (
        await db.execute(
            select(Gallery.id, Gallery.title, Tag.id, Tag.namespace, Tag.name, GalleryTag.confidence)
            .join(GalleryTag, GalleryTag.gallery_id == Gallery.id)
            .join(Tag, Tag.id == GalleryTag.tag_id)
            .where(GalleryTag.source == "metadata", gallery_access_filter(auth))
        )
    ).all()
    ai_rows = (
        await db.execute(
            select(
                Gallery.id,
                Gallery.title,
                Tag.id,
                Tag.namespace,
                Tag.name,
                func.max(ImageTag.confidence),
            )
            .join(Image, Image.gallery_id == Gallery.id)
            .join(ImageTag, ImageTag.image_id == Image.id)
            .join(Tag, Tag.id == ImageTag.tag_id)
            .where(gallery_access_filter(auth))
            .group_by(Gallery.id, Gallery.title, Tag.id, Tag.namespace, Tag.name)
        )
    ).all()
    combined: dict[tuple[int, int], dict] = {}
    for gallery_id, title, tag_id, namespace, name, confidence in metadata_rows:
        combined[(gallery_id, tag_id)] = {
            "gallery_id": gallery_id,
            "gallery_title": title,
            "tag_id": tag_id,
            "namespace": namespace,
            "name": name,
            "metadata_confidence": float(confidence or 0),
            "ai_confidence": 0.0,
        }
    for gallery_id, title, tag_id, namespace, name, confidence in ai_rows:
        row = combined.setdefault(
            (gallery_id, tag_id),
            {
                "gallery_id": gallery_id,
                "gallery_title": title,
                "tag_id": tag_id,
                "namespace": namespace,
                "name": name,
                "metadata_confidence": 0.0,
                "ai_confidence": 0.0,
            },
        )
        row["ai_confidence"] = float(confidence or 0)
    anomalies = []
    for row in combined.values():
        difference = abs(row["ai_confidence"] - row["metadata_confidence"])
        if difference < min_difference:
            continue
        row["difference"] = round(difference, 4)
        row["suggestion"] = (
            "review_ai_only" if row["ai_confidence"] > row["metadata_confidence"] else "review_metadata_only"
        )
        anomalies.append(row)
    anomalies.sort(key=lambda item: (-item["difference"], item["gallery_id"], item["tag_id"]))
    return {"anomalies": anomalies[:limit], "total": len(anomalies), "cached": False}


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

    Rejected with 409 if still referenced by gallery_tags or image_tags —
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
        it_count = (
            await session.execute(select(func.count()).select_from(ImageTag).where(ImageTag.tag_id == tag_id))
        ).scalar()
        if gt_count or it_count:
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
