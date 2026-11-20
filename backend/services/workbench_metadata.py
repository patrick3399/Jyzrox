"""Metadata provenance and locking primitives for the Library Workbench."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import Gallery, GalleryMetadataChange, GalleryMetadataFieldState
from services.gallery_categories import load_category_map, resolve_with_map
from services.workbench_source_tags import apply_source_tags as apply_source_tags

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
    category_map = await load_category_map(db) if "category" in changes else {}

    # Validate and resolve every requested value up front so a bad value cannot
    # leave a partial write behind. The resolved value is the same for every
    # selected gallery.
    resolved: dict[str, Any] = {}
    for field_name, (mode, requested_value) in changes.items():
        if mode == "keep":
            continue
        value = None if mode == "clear" else requested_value
        if field_name == "visibility":
            if mode == "clear" or value not in {"public", "private"}:
                raise HTTPException(status_code=400, detail="visibility must be public or private")
        elif value is not None and not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{field_name} must be a string or null")
        if field_name == "category" and value is not None:
            # Manual input is limited to the category registry. An empty or
            # whitespace-only value clears the category; any other value that
            # is not registered is rejected rather than silently stored as NULL
            # (which would wipe the category of every selected gallery).
            if not value.strip():
                value = None
            else:
                canonical = resolve_with_map(value, category_map)
                if canonical is None:
                    raise HTTPException(status_code=400, detail=f"Unknown category: {value}")
                value = canonical
        resolved[field_name] = value

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
        for field_name, value in resolved.items():
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
