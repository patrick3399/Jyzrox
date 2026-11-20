"""Dataset counting, serialization and filter evaluation helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from db.models import (
    Blob,
    Dataset,
    DatasetImage,
    Gallery,
    Image,
)
from services.dataset_schemas import DatasetFilterConfig


async def _counts(db: AsyncSession, dataset_id: int, auth: dict) -> tuple[int, int, int]:
    rows = (
        await db.execute(
            select(DatasetImage.state, Image.gallery_id)
            .join(Image, Image.id == DatasetImage.image_id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .where(
                DatasetImage.dataset_id == dataset_id,
                Image.visibility == "active",
                Image.blob_sha256.is_not(None),
                gallery_access_filter(auth),
            )
        )
    ).all()
    included = [row for row in rows if row.state == "included"]
    return len(included), len({row.gallery_id for row in included}), len(rows) - len(included)


def _serialize_dataset(dataset: Dataset, member_count: int, gallery_count: int, excluded_count: int) -> dict:
    return {
        "id": dataset.id,
        "name": dataset.name,
        "description": dataset.description,
        "selection_spec": dataset.selection_spec or {},
        "member_count": member_count,
        "gallery_count": gallery_count,
        "excluded_count": excluded_count,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


_AUTO_EXCLUSION_REASONS = frozenset({"min_resolution", "aspect_ratio", "phash_duplicate"})


async def _dataset_filter_rows(db: AsyncSession, dataset_id: int, auth: dict) -> list:
    return list(
        (
            await db.execute(
                select(DatasetImage, Blob)
                .join(Image, Image.id == DatasetImage.image_id)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .join(Blob, Blob.sha256 == Image.blob_sha256)
                .where(
                    DatasetImage.dataset_id == dataset_id,
                    Image.visibility == "active",
                    gallery_access_filter(auth),
                )
                .order_by(Image.id)
            )
        ).all()
    )


def _filter_reason(blob: Blob, config: DatasetFilterConfig) -> tuple[str | None, bool]:
    width = blob.width
    height = blob.height
    if config.min_width is None and config.min_height is None and config.max_aspect_ratio is None:
        return None, False
    if config.min_width is not None and width is None:
        return None, True
    if config.min_height is not None and height is None:
        return None, True
    if (config.min_width is not None and width is not None and width < config.min_width) or (
        config.min_height is not None and height is not None and height < config.min_height
    ):
        return "min_resolution", False
    if config.max_aspect_ratio is not None:
        if width is None or height is None or width <= 0 or height <= 0:
            return None, True
        aspect_ratio = max(width / height, height / width)
        if aspect_ratio > config.max_aspect_ratio:
            return "aspect_ratio", False
    return None, False


def _phash_distance(left: int, right: int) -> int:
    mask = (1 << 64) - 1
    return ((left & mask) ^ (right & mask)).bit_count()


def _evaluate_filters(rows: list, config: DatasetFilterConfig) -> tuple[list[tuple[DatasetImage, str | None]], dict]:
    decisions: list[tuple[DatasetImage, str | None]] = []
    reason_counts = {"min_resolution": 0, "aspect_ratio": 0, "phash_duplicate": 0}
    manual_excluded = 0
    unknown_dimensions = 0
    unknown_phash = 0
    newly_excluded = 0
    would_restore = 0

    retained_phashes: list[int] = []
    for member, blob in rows:
        is_auto_excluded = member.exclusion_reason in _AUTO_EXCLUSION_REASONS
        if member.state == "excluded" and not is_auto_excluded:
            manual_excluded += 1
            continue
        reason, dimensions_unknown = _filter_reason(blob, config)
        if dimensions_unknown:
            unknown_dimensions += 1
        if reason is None and config.phash_distance is not None:
            if blob.phash_int is None:
                unknown_phash += 1
            elif any(
                _phash_distance(blob.phash_int, previous) <= config.phash_distance for previous in retained_phashes
            ):
                reason = "phash_duplicate"
            else:
                retained_phashes.append(blob.phash_int)
        if reason is not None:
            reason_counts[reason] += 1
            if member.state == "included":
                newly_excluded += 1
        elif is_auto_excluded:
            would_restore += 1
        decisions.append((member, reason))

    auto_excluded = sum(reason_counts.values())
    return decisions, {
        "total": len(rows),
        "auto_excluded": auto_excluded,
        "newly_excluded": newly_excluded,
        "would_restore": would_restore,
        "manual_excluded": manual_excluded,
        "remaining": len(rows) - manual_excluded - auto_excluded,
        "unknown_dimensions": unknown_dimensions,
        "unknown_phash": unknown_phash,
        "reasons": reason_counts,
    }
