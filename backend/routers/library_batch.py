"""Library split from routers/library.py (library_batch)."""

from typing import cast as typing_cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case as sql_case
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import literal as sql_literal

from core.auth import require_role
from core.database import get_db
from db.models import (
    GalleryTag,
    Tag,
    UserFavorite,
    UserRating,
    UserReadingList,
)
from services.library_batch_ops import BatchAction
from services.library_batch_ops import batch_delete_galleries as _batch_delete_galleries

_member = require_role("member")
router = APIRouter()


@router.post("/galleries/batch")
async def batch_galleries(
    body: BatchAction,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Batch operations on multiple galleries."""
    if len(body.gallery_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 galleries per batch")
    if not body.gallery_ids:
        raise HTTPException(status_code=400, detail="No gallery IDs provided")
    if body.action == "rate" and (body.rating is None or body.rating < 0 or body.rating > 5):
        raise HTTPException(status_code=400, detail="Rating must be 0-5 for rate action")

    # Deduplicate while preserving order
    gallery_ids = list(dict.fromkeys(body.gallery_ids))

    if body.action == "favorite":
        for gid in gallery_ids:
            stmt = (
                pg_insert(UserFavorite)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gid,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(gallery_ids)}

    elif body.action == "unfavorite":
        result = await db.execute(
            sa_delete(UserFavorite).where(
                UserFavorite.user_id == auth["user_id"],
                UserFavorite.gallery_id.in_(gallery_ids),
            )
        )
        await db.commit()
        return {"status": "ok", "affected": typing_cast(CursorResult, result).rowcount}

    elif body.action == "add_to_reading_list":
        for gid in gallery_ids:
            stmt = (
                pg_insert(UserReadingList)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gid,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(gallery_ids)}

    elif body.action == "remove_from_reading_list":
        result = await db.execute(
            sa_delete(UserReadingList).where(
                UserReadingList.user_id == auth["user_id"],
                UserReadingList.gallery_id.in_(gallery_ids),
            )
        )
        await db.commit()
        return {"status": "ok", "affected": typing_cast(CursorResult, result).rowcount}

    elif body.action == "rate":
        for gid in gallery_ids:
            if body.rating == 0:
                await db.execute(
                    sa_delete(UserRating).where(
                        UserRating.user_id == auth["user_id"],
                        UserRating.gallery_id == gid,
                    )
                )
            else:
                stmt = (
                    pg_insert(UserRating)
                    .values(
                        user_id=auth["user_id"],
                        gallery_id=gid,
                        rating=body.rating,
                    )
                    .on_conflict_do_update(
                        index_elements=["user_id", "gallery_id"],
                        set_={"rating": body.rating, "rated_at": func.now()},
                    )
                )
                await db.execute(stmt)
        await db.commit()
        return {"status": "ok", "affected": len(gallery_ids)}

    elif body.action == "add_to_collection":
        if body.collection_id is None:
            raise HTTPException(status_code=400, detail="collection_id required for add_to_collection")
        from core.events import EventType, emit_safe
        from db.models import Collection
        from services.collection_membership import add_galleries_to_collection

        collection = await db.get(Collection, body.collection_id)
        if not collection or collection.user_id != auth["user_id"]:
            raise HTTPException(status_code=404, detail="Collection not found")

        added, denied = await add_galleries_to_collection(db, collection, gallery_ids, auth)
        await db.commit()
        await emit_safe(
            EventType.COLLECTION_UPDATED,
            actor_user_id=auth["user_id"],
            resource_type="collection",
            resource_id=body.collection_id,
        )
        return {"status": "ok", "affected": added, "denied": denied}

    elif body.action == "add_tags":
        if not body.tags:
            raise HTTPException(status_code=400, detail="tags required for add_tags action")
        from services.tag_helpers import parse_tag_strings, rebuild_gallery_tags_array

        parsed = parse_tag_strings(body.tags)
        if not parsed:
            return {"status": "ok", "affected": 0}

        # Upsert tags ONCE (count=0 to just ensure they exist without inflating counts)
        tag_values = [{"namespace": ns, "name": name, "count": 0} for ns, name in parsed]
        tag_stmt = (
            pg_insert(Tag)
            .values(tag_values)
            .on_conflict_do_nothing(index_elements=["namespace", "name"])
            .returning(Tag.id)
        )
        await db.execute(tag_stmt)

        # Resolve tag IDs in one query
        tag_ids = (await db.execute(select(Tag.id).where(tuple_(Tag.namespace, Tag.name).in_(parsed)))).scalars().all()

        if not tag_ids:
            return {"status": "ok", "affected": 0}

        # Upsert gallery_tags for ALL galleries at once
        gt_values = [
            {"gallery_id": gid, "tag_id": tid, "confidence": 1.0, "source": "manual"}
            for gid in gallery_ids
            for tid in tag_ids
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
            await db.execute(gt_stmt)

        # Rebuild tags_array for each gallery
        for gid in gallery_ids:
            await rebuild_gallery_tags_array(db, gid)

        # Recalculate counts for affected tags (correct, not inflated)
        for tid in tag_ids:
            count_result = await db.execute(select(func.count()).where(GalleryTag.tag_id == tid))
            actual_count = count_result.scalar_one()
            await db.execute(sa_update(Tag).where(Tag.id == tid).values(count=actual_count))

        await db.commit()
        return {"status": "ok", "affected": len(gallery_ids)}

    elif body.action == "remove_tags":
        if not body.tags:
            raise HTTPException(status_code=400, detail="tags required for remove_tags action")
        from services.tag_helpers import parse_tag_strings, rebuild_gallery_tags_array

        parsed = parse_tag_strings(body.tags)
        if not parsed:
            return {"status": "ok", "affected": 0}

        # Resolve tag IDs once
        ns_name_filter = or_(*[(Tag.namespace == ns) & (Tag.name == name) for ns, name in parsed])
        tag_ids = (await db.execute(select(Tag.id).where(ns_name_filter))).scalars().all()

        if not tag_ids:
            return {"status": "ok", "affected": 0}

        # Bulk delete gallery_tags across all galleries in one statement
        del_result = await db.execute(
            sa_delete(GalleryTag).where(
                GalleryTag.gallery_id.in_(gallery_ids),
                GalleryTag.tag_id.in_(tag_ids),
                GalleryTag.source == "manual",
            )
        )
        removed = typing_cast(CursorResult, del_result).rowcount

        # Recalculate counts for affected tags
        for tid in tag_ids:
            count_result = await db.execute(select(func.count()).where(GalleryTag.tag_id == tid))
            actual_count = count_result.scalar_one()
            await db.execute(sa_update(Tag).where(Tag.id == tid).values(count=actual_count))

        # Rebuild tags_array for each gallery
        for gid in gallery_ids:
            await rebuild_gallery_tags_array(db, gid)

        await db.commit()
        return {"status": "ok", "affected": removed}

    elif body.action == "delete":
        return await _batch_delete_galleries(db, gallery_ids, auth)
