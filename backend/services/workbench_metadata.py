"""Metadata provenance and locking primitives for the Library Workbench."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import Gallery, GalleryMetadataChange, GalleryMetadataFieldState, GalleryTag, Tag

EDITABLE_SCALAR_FIELDS = frozenset(
    {"title", "title_jpn", "category", "language", "artist_id", "uploader", "visibility"}
)
SOURCE_SCALAR_FIELDS = frozenset(
    {
        "title",
        "title_jpn",
        "category",
        "language",
        "artist_id",
        "uploader",
        "visibility",
        "pages",
        "posted_at",
        "rating",
    }
)


def metadata_json_value(value: Any) -> Any:
    """Convert scalar ORM values to JSON-safe provenance values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def ensure_gallery_write_access(auth: dict, gallery: Gallery) -> None:
    """Apply the same owner rules as the existing library mutation routes."""
    if auth["role"] == "admin":
        return
    if gallery.created_by_user_id is None or gallery.created_by_user_id == auth["user_id"]:
        return
    raise HTTPException(status_code=403, detail="You do not have permission to modify this gallery")


async def load_writable_galleries(
    db: AsyncSession,
    gallery_ids: Sequence[int],
    auth: dict,
    *,
    lock_rows: bool = False,
) -> list[Gallery]:
    """Load an explicit selection and reject missing, trashed, or non-writable rows."""
    ordered_ids = list(dict.fromkeys(gallery_ids))
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="At least one gallery is required")

    stmt = select(Gallery).where(Gallery.id.in_(ordered_ids), Gallery.deleted_at.is_(None))
    if lock_rows:
        stmt = stmt.with_for_update()
    rows = (await db.execute(stmt)).scalars().all()
    by_id = {gallery.id: gallery for gallery in rows}
    if len(by_id) != len(ordered_ids):
        raise HTTPException(status_code=404, detail="One or more galleries were not found")

    ordered = [by_id[gallery_id] for gallery_id in ordered_ids]
    for gallery in ordered:
        ensure_gallery_write_access(auth, gallery)
    return ordered


async def load_accessible_galleries(
    db: AsyncSession,
    gallery_ids: Sequence[int],
    auth: dict,
) -> list[Gallery]:
    """Load an explicit active selection using read-access rules."""
    ordered_ids = list(dict.fromkeys(gallery_ids))
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="At least one gallery is required")
    rows = (
        (await db.execute(select(Gallery).where(Gallery.id.in_(ordered_ids), gallery_access_filter(auth))))
        .scalars()
        .all()
    )
    by_id = {gallery.id: gallery for gallery in rows}
    if len(by_id) != len(ordered_ids):
        raise HTTPException(status_code=404, detail="One or more galleries were not found")
    return [by_id[gallery_id] for gallery_id in ordered_ids]


async def apply_manual_scalar_changes(
    db: AsyncSession,
    galleries: Sequence[Gallery],
    changes: Mapping[str, tuple[str, Any]],
    *,
    actor_user_id: int,
    operation_id: UUID | None,
    lock_fields: bool = True,
) -> int:
    """Apply tri-state scalar edits and append provenance history."""
    unknown = set(changes) - EDITABLE_SCALAR_FIELDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported metadata fields: {', '.join(sorted(unknown))}")

    now = datetime.now(UTC)
    changed_count = 0
    field_names = list(changes)
    gallery_ids = [gallery.id for gallery in galleries]
    existing_states = {
        (state.gallery_id, state.field_name): state
        for state in (
            await db.execute(
                select(GalleryMetadataFieldState).where(
                    GalleryMetadataFieldState.gallery_id.in_(gallery_ids),
                    GalleryMetadataFieldState.field_name.in_(field_names),
                )
            )
        ).scalars()
    }
    for gallery in galleries:
        for field_name, (mode, requested_value) in changes.items():
            if mode == "keep":
                continue
            value = None if mode == "clear" else requested_value
            if field_name == "visibility":
                if mode == "clear" or value not in {"public", "private"}:
                    raise HTTPException(status_code=400, detail="visibility must be public or private")
            elif value is not None and not isinstance(value, str):
                raise HTTPException(status_code=400, detail=f"{field_name} must be a string or null")

            old_value = getattr(gallery, field_name)
            state = existing_states.get((gallery.id, field_name))
            source_value = state.source_value if state else metadata_json_value(old_value)
            if state is None:
                state = GalleryMetadataFieldState(gallery_id=gallery.id, field_name=field_name)
                db.add(state)
                existing_states[(gallery.id, field_name)] = state
            state.origin = "manual"
            state.locked = lock_fields
            state.source_value = source_value
            state.updated_by_user_id = actor_user_id
            state.updated_at = now

            if old_value == value:
                continue
            setattr(gallery, field_name, value)
            gallery.metadata_updated_at = now
            db.add(
                GalleryMetadataChange(
                    gallery_id=gallery.id,
                    field_name=field_name,
                    old_value=metadata_json_value(old_value),
                    new_value=metadata_json_value(value),
                    origin="manual",
                    actor_user_id=actor_user_id,
                    operation_id=operation_id,
                )
            )
            changed_count += 1
    return changed_count


async def apply_source_scalar_metadata(
    db: AsyncSession,
    gallery: Gallery,
    values: Mapping[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Apply source refreshes while preserving manually locked values.

    Locked fields retain their displayed value and receive a pending source
    value for the Inspector diff. Unlocked fields are updated normally.
    """
    now = datetime.now(UTC)
    changed_fields: list[str] = []
    pending: dict[str, dict[str, Any]] = {}
    for field_name, source_value in values.items():
        if field_name not in SOURCE_SCALAR_FIELDS or source_value is None:
            continue
        state = await db.get(GalleryMetadataFieldState, (gallery.id, field_name))
        current_value = getattr(gallery, field_name)
        if state is not None and state.locked:
            state.source_value = metadata_json_value(source_value)
            state.updated_at = now
            if current_value != source_value:
                pending[field_name] = {"current": current_value, "source": source_value}
            continue

        if state is None:
            state = GalleryMetadataFieldState(gallery_id=gallery.id, field_name=field_name)
            db.add(state)
        state.origin = "source"
        state.locked = False
        state.source_value = metadata_json_value(source_value)
        state.updated_at = now
        if current_value == source_value:
            continue
        setattr(gallery, field_name, source_value)
        db.add(
            GalleryMetadataChange(
                gallery_id=gallery.id,
                field_name=field_name,
                old_value=metadata_json_value(current_value),
                new_value=metadata_json_value(source_value),
                origin="source",
            )
        )
        changed_fields.append(field_name)

    gallery.metadata_updated_at = now
    return changed_fields, pending


async def apply_source_tags(db: AsyncSession, gallery: Gallery, tag_strings: Sequence[str]) -> bool:
    """Replace source-owned tags while preserving manual and AI relationships."""
    from services.tag_helpers import parse_tag_strings

    parsed = parse_tag_strings(list(tag_strings))
    tags: list[Tag] = []
    if parsed:
        tags = (
            (
                await db.execute(
                    select(Tag).where(
                        or_(*[(Tag.namespace == namespace) & (Tag.name == name) for namespace, name in parsed])
                    )
                )
            )
            .scalars()
            .all()
        )
    by_value = {(tag.namespace, tag.name): tag for tag in tags}
    for namespace, name in parsed:
        if (namespace, name) not in by_value:
            tag = Tag(namespace=namespace, name=name, count=0)
            db.add(tag)
            await db.flush()
            by_value[(namespace, name)] = tag

    desired_ids = {tag.id for tag in by_value.values()}
    existing = (await db.execute(select(GalleryTag).where(GalleryTag.gallery_id == gallery.id))).scalars().all()
    source_rows = {row.tag_id: row for row in existing if row.source == "metadata"}
    affected_ids = set(source_rows) | desired_ids
    for tag_id, row in source_rows.items():
        if tag_id not in desired_ids:
            await db.delete(row)
    existing_ids = {row.tag_id for row in existing}
    for tag_id in desired_ids:
        if tag_id not in existing_ids:
            db.add(GalleryTag(gallery_id=gallery.id, tag_id=tag_id, confidence=1.0, source="metadata"))
        elif tag_id in source_rows:
            source_rows[tag_id].confidence = 1.0
    await db.flush()

    rows = (
        await db.execute(
            select(Tag.namespace, Tag.name)
            .join(GalleryTag, GalleryTag.tag_id == Tag.id)
            .where(GalleryTag.gallery_id == gallery.id)
            .order_by(Tag.namespace, Tag.name)
        )
    ).all()
    rebuilt = [f"{row.namespace}:{row.name}" for row in rows]
    changed = rebuilt != list(gallery.tags_array or [])
    gallery.tags_array = rebuilt
    for tag_id in affected_ids:
        count = (
            await db.execute(select(func.count()).select_from(GalleryTag).where(GalleryTag.tag_id == tag_id))
        ).scalar_one()
        tag = next((value for value in by_value.values() if value.id == tag_id), None)
        if tag is None:
            tag = await db.get(Tag, tag_id)
        if tag is not None:
            tag.count = count
    return changed
