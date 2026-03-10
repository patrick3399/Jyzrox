"""Tag, Alias, and Implication management endpoints."""

import base64
import json
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.database import async_session, get_db
from db.models import BlockedTag, Gallery, Tag, TagAlias, TagImplication, TagTranslation

router = APIRouter(tags=["tags"])


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
        safe_prefix = prefix.replace('%', '\\%').replace('_', '\\_')
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
async def create_alias(req: AliasRequest, _: dict = Depends(require_auth)):
    async with async_session() as session:
        tag = (await session.execute(select(Tag.id).where(Tag.id == req.canonical_id))).fetchone()
        if not tag:
            raise HTTPException(status_code=404, detail="Canonical tag not found")

        # Upsert alias
        existing = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == req.alias_namespace,
                    TagAlias.alias_name == req.alias_name,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.canonical_id = req.canonical_id
        else:
            session.add(
                TagAlias(
                    alias_namespace=req.alias_namespace,
                    alias_name=req.alias_name,
                    canonical_id=req.canonical_id,
                )
            )
        await session.commit()
    return {"status": "ok"}


@router.delete("/aliases")
async def delete_alias(
    alias_namespace: str = Query(...),
    alias_name: str = Query(...),
    _: dict = Depends(require_auth),
):
    async with async_session() as session:
        alias = (
            await session.execute(
                select(TagAlias).where(
                    TagAlias.alias_namespace == alias_namespace,
                    TagAlias.alias_name == alias_name,
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
            await session.execute(
                select(TagImplication.consequent_id).where(TagImplication.antecedent_id == current)
            )
        ).scalars().all()
        queue.extend(r for r in rows if r not in visited)
    # If we hit the limit, conservatively assume a cycle exists
    return len(visited) >= max_depth


@router.post("/implications")
async def create_implication(req: ImplicationRequest, _: dict = Depends(require_auth)):
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
    _: dict = Depends(require_auth),
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
    _: dict = Depends(require_auth),
):
    """Return tags matching the given prefix, ordered by count DESC."""
    if not q:
        return []

    async with async_session() as session:
        # Support 'namespace:name' prefix format
        if ":" in q:
            ns, name_prefix = q.split(":", 1)
            query = (
                select(Tag)
                .where(Tag.namespace.ilike(f"{ns}%"), Tag.name.ilike(f"{name_prefix}%"))
                .order_by(desc(Tag.count), desc(Tag.id))
                .limit(limit)
            )
        else:
            query = (
                select(Tag)
                .where(Tag.name.ilike(f"{q}%"))
                .order_by(desc(Tag.count), desc(Tag.id))
                .limit(limit)
            )
        rows = (await session.execute(query)).scalars().all()

    return [{"id": r.id, "namespace": r.namespace, "name": r.name, "count": r.count} for r in rows]


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

    async with async_session() as session:
        # Fetch all matching translations in one query
        from sqlalchemy import tuple_

        rows = (
            await session.execute(
                select(TagTranslation).where(
                    TagTranslation.language == language,
                    tuple_(TagTranslation.namespace, TagTranslation.name).in_(tag_pairs),
                )
            )
        ).scalars().all()

    result = {}
    for r in rows:
        result[f"{r.namespace}:{r.name}"] = r.translation
    return result


@router.post("/translations")
async def upsert_translation(
    body: TranslationUpsert,
    _: dict = Depends(require_auth),
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
    _: dict = Depends(require_auth),
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
        rows = (
            await session.execute(
                select(BlockedTag).where(BlockedTag.user_id == user_id)
            )
        ).scalars().all()
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


# ── AI Re-tag ─────────────────────────────────────────────────────────


@router.post("/retag/{gallery_id}")
async def retag_gallery(
    gallery_id: int,
    request: Request,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue AI tagging job for all images in a gallery."""
    from core.config import settings as app_settings

    if not app_settings.tag_model_enabled:
        raise HTTPException(status_code=400, detail="AI tagging is not enabled (TAG_MODEL_ENABLED=false)")

    # Verify gallery exists
    gallery = await db.get(Gallery, gallery_id)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found")

    arq = request.app.state.arq
    await arq.enqueue_job("tag_job", gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}


@router.post("/retag-all")
async def retag_all_galleries(
    request: Request,
    _: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue AI tagging jobs for ALL galleries (batch re-tag).

    Uses chunked queries and Redis pipeline to avoid loading all IDs
    into memory and doing 100K individual roundtrips.
    """
    from core.config import settings as app_settings

    if not app_settings.tag_model_enabled:
        raise HTTPException(status_code=400, detail="AI tagging is not enabled (TAG_MODEL_ENABLED=false)")

    arq = request.app.state.arq
    enqueued = 0
    CHUNK = 1000
    offset = 0

    while True:
        chunk = (await db.execute(
            select(Gallery.id).order_by(Gallery.id).offset(offset).limit(CHUNK)
        )).scalars().all()

        if not chunk:
            break

        for gid in chunk:
            await arq.enqueue_job("tag_job", gid)
            enqueued += 1

        offset += CHUNK

    return {"status": "enqueued", "total": enqueued}
