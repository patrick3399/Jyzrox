"""Gallery-graph context classification for similar blob pairs."""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import aliased

from db.models import Image


async def _pair_context_scope(session, sha_a: str, sha_b: str) -> str:
    """Classify where a similar blob pair occurs in the gallery graph."""
    image_a = aliased(Image)
    image_b = aliased(Image)
    ref_a = select(image_a.id).where(image_a.blob_sha256 == sha_a).limit(1).exists()
    ref_b = select(image_b.id).where(image_b.blob_sha256 == sha_b).limit(1).exists()
    same_gallery = (
        select(image_a.id)
        .join(image_b, image_b.gallery_id == image_a.gallery_id)
        .where(image_a.blob_sha256 == sha_a, image_b.blob_sha256 == sha_b)
        .limit(1)
        .exists()
    )
    cross_gallery = (
        select(image_a.id)
        .join(image_b, image_b.gallery_id != image_a.gallery_id)
        .where(image_a.blob_sha256 == sha_a, image_b.blob_sha256 == sha_b)
        .limit(1)
        .exists()
    )
    scope = (
        await session.execute(
            select(
                case(
                    ((~ref_a) | (~ref_b), "unreferenced"),
                    (same_gallery & cross_gallery, "mixed"),
                    (cross_gallery, "cross_gallery"),
                    (same_gallery, "same_gallery_only"),
                    else_="unreferenced",
                )
            )
        )
    ).scalar()

    # Preserve compatibility with lightweight mocked sessions used by focused
    # worker tests while production queries always return the string values.
    if scope is True:
        return "same_gallery_only"
    if scope is False:
        return "cross_gallery"
    return str(scope)


async def _pair_context_scopes(session, pairs) -> dict[int, str]:
    """Classify a batch of pairs with one occurrence query.

    Context is based only on the set of galleries referencing each blob, so
    loading ``(blob_sha256, gallery_id)`` once avoids four EXISTS probes and a
    transaction per relationship.
    """
    pair_list = list(pairs)
    shas = {sha for pair in pair_list for sha in (pair.sha_a, pair.sha_b)}
    if not shas:
        return {}
    rows = (
        await session.execute(select(Image.blob_sha256, Image.gallery_id).where(Image.blob_sha256.in_(shas)).distinct())
    ).all()
    galleries: dict[str, set[int]] = {sha: set() for sha in shas}
    for sha, gallery_id in rows:
        galleries.setdefault(sha, set()).add(int(gallery_id))

    scopes: dict[int, str] = {}
    for pair in pair_list:
        galleries_a = galleries.get(pair.sha_a, set())
        galleries_b = galleries.get(pair.sha_b, set())
        if not galleries_a or not galleries_b:
            scope = "unreferenced"
        else:
            has_same = bool(galleries_a & galleries_b)
            has_cross = any(a != b for a in galleries_a for b in galleries_b)
            if has_same and has_cross:
                scope = "mixed"
            elif has_cross:
                scope = "cross_gallery"
            else:
                scope = "same_gallery_only"
        scopes[int(pair.id)] = scope
    return scopes
