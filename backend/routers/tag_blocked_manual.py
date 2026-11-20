"""Blocked tag, manual tagging, and EhTag import endpoints."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case as sql_case
from sqlalchemy import delete, or_, select
from sqlalchemy import literal as sql_literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import has_gallery_write_access, require_auth, require_role
from core.database import async_session, get_db
from db.models import BlockedTag, Gallery, GalleryTag, Tag

router = APIRouter()
_admin = require_role("admin")
_member = require_role("member")


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
