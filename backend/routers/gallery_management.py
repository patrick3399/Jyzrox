"""Gallery sharing and version-management endpoints."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, has_gallery_write_access, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    Blob,
    Gallery,
    GalleryPermission,
    GalleryShareLink,
    GalleryVersion,
    Image,
    User,
)
from services.cas import resolve_blob_path

router = APIRouter(tags=["gallery-management"])
_member = require_role("member")


class VisibilityPatch(BaseModel):
    visibility: str
    permissions: list[dict] = Field(default_factory=list, max_length=100)


class ShareCreate(BaseModel):
    expires_in_hours: int | None = Field(default=168, ge=1, le=8760)
    filter_r18: bool = True


class VersionCreate(BaseModel):
    gallery_id: int


async def _gallery(db: AsyncSession, gallery_id: int, auth: dict) -> Gallery:
    gallery = (
        await db.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
    ).scalar_one_or_none()
    if gallery is None:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return gallery


async def _require_write(db: AsyncSession, gallery: Gallery, auth: dict) -> None:
    if not await has_gallery_write_access(db, gallery.id, gallery.created_by_user_id, auth):
        raise HTTPException(status_code=403, detail="Gallery write access is required")


@router.get("/galleries/{gallery_id}/sharing")
async def get_sharing(gallery_id: int, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)):
    gallery = await _gallery(db, gallery_id, auth)
    await _require_write(db, gallery, auth)
    permissions = (
        await db.execute(
            select(GalleryPermission, User.username)
            .join(User, User.id == GalleryPermission.user_id)
            .where(GalleryPermission.gallery_id == gallery_id)
        )
    ).all()
    links = (
        (
            await db.execute(
                select(GalleryShareLink)
                .where(GalleryShareLink.gallery_id == gallery_id, GalleryShareLink.revoked_at.is_(None))
                .order_by(GalleryShareLink.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "visibility": gallery.visibility,
        "permissions": [
            {"user_id": p.user_id, "username": username, "can_edit": p.can_edit} for p, username in permissions
        ],
        "links": [
            {
                "id": link.id,
                "expires_at": link.expires_at.isoformat() if link.expires_at else None,
                "filter_r18": link.filter_r18,
                "created_at": link.created_at.isoformat(),
            }
            for link in links
        ],
    }


@router.patch("/galleries/{gallery_id}/sharing")
async def update_sharing(
    gallery_id: int, body: VisibilityPatch, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)
):
    if body.visibility not in {"public", "private"}:
        raise HTTPException(status_code=400, detail="visibility must be public or private")
    gallery = await _gallery(db, gallery_id, auth)
    await _require_write(db, gallery, auth)
    gallery.visibility = body.visibility
    await db.execute(delete(GalleryPermission).where(GalleryPermission.gallery_id == gallery_id))
    seen: set[int] = set()
    for raw in body.permissions:
        user_id = raw.get("user_id")
        if not isinstance(user_id, int) or user_id in seen or user_id == gallery.created_by_user_id:
            continue
        if await db.get(User, user_id) is None:
            raise HTTPException(status_code=400, detail=f"Unknown user_id: {user_id}")
        seen.add(user_id)
        db.add(GalleryPermission(gallery_id=gallery_id, user_id=user_id, can_edit=bool(raw.get("can_edit"))))
    await db.commit()
    await emit_safe(
        EventType.GALLERY_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="gallery",
        resource_id=gallery_id,
        action="sharing_updated",
    )
    return {"status": "ok", "visibility": gallery.visibility}


@router.post("/galleries/{gallery_id}/shares", status_code=201)
async def create_share(
    gallery_id: int, body: ShareCreate, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)
):
    gallery = await _gallery(db, gallery_id, auth)
    await _require_write(db, gallery, auth)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=body.expires_in_hours) if body.expires_in_hours else None
    link = GalleryShareLink(
        gallery_id=gallery_id,
        created_by_user_id=auth["user_id"],
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=expires_at,
        filter_r18=body.filter_r18,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return {
        "id": link.id,
        "token": token,
        "url": f"/share/{token}",
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.delete("/galleries/{gallery_id}/shares/{link_id}")
async def revoke_share(
    gallery_id: int, link_id: int, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)
):
    gallery = await _gallery(db, gallery_id, auth)
    await _require_write(db, gallery, auth)
    link = await db.get(GalleryShareLink, link_id)
    if link is None or link.gallery_id != gallery_id:
        raise HTTPException(status_code=404, detail="Share link not found")
    link.revoked_at = datetime.now(UTC)
    await db.commit()
    return {"status": "ok"}


async def _share(db: AsyncSession, token: str) -> tuple[GalleryShareLink, Gallery]:
    row = (
        await db.execute(
            select(GalleryShareLink, Gallery)
            .join(Gallery, Gallery.id == GalleryShareLink.gallery_id)
            .where(
                GalleryShareLink.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                GalleryShareLink.revoked_at.is_(None),
                Gallery.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    link, gallery = row
    if link.expires_at is not None:
        expires_at = link.expires_at.replace(tzinfo=link.expires_at.tzinfo or UTC)
        if expires_at <= datetime.now(UTC):
            raise HTTPException(status_code=410, detail="Share link expired")
    return link, gallery


def _is_r18(tags: list[str]) -> bool:
    normalized = {tag.strip().lower() for tag in tags}
    return bool(normalized & {"r18", "rating:explicit", "rating:questionable", "content:r18"})


@router.get("/shares/{token}")
async def public_share(token: str, db: AsyncSession = Depends(get_db)):
    link, gallery = await _share(db, token)
    if link.filter_r18 and _is_r18(gallery.tags_array or []):
        raise HTTPException(status_code=451, detail="This shared gallery is hidden by the R18 content filter")
    images = (
        await db.execute(
            select(Image.id, Image.page_num)
            .where(Image.gallery_id == gallery.id, Image.visibility == "active")
            .order_by(Image.page_num)
        )
    ).all()
    return {
        "gallery": {
            "id": gallery.id,
            "title": gallery.title,
            "source": gallery.source,
            "source_id": gallery.source_id,
            "pages": len(images),
            "tags": [] if link.filter_r18 else gallery.tags_array or [],
        },
        "images": [
            {"id": image_id, "page_num": page_num, "url": f"/api/gallery-management/shares/{token}/images/{image_id}"}
            for image_id, page_num in images
        ],
    }


@router.get("/shares/{token}/images/{image_id}")
async def public_share_image(token: str, image_id: int, db: AsyncSession = Depends(get_db)):
    link, gallery = await _share(db, token)
    if link.filter_r18 and _is_r18(gallery.tags_array or []):
        raise HTTPException(status_code=451, detail="R18 content is filtered")
    row = (
        await db.execute(
            select(Image, Blob)
            .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Image.id == image_id, Image.gallery_id == gallery.id, Image.visibility == "active")
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")
    image, blob = row
    if blob is None and not image.external_path:
        raise HTTPException(status_code=404, detail="Image not found")
    # A pending link page has no blob: serve the row's own external_path.
    path = resolve_blob_path(blob, image.external_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(path, filename=image.filename or path.name, content_disposition_type="inline")


@router.get("/galleries/{gallery_id}/versions")
async def list_versions(gallery_id: int, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)):
    gallery = await _gallery(db, gallery_id, auth)
    version = await db.get(GalleryVersion, gallery.id)
    if version is None:
        return {"group_id": None, "versions": []}
    rows = (
        (
            await db.execute(
                select(Gallery)
                .join(GalleryVersion, GalleryVersion.gallery_id == Gallery.id)
                .where(GalleryVersion.group_id == version.group_id, gallery_access_filter(auth))
                .order_by(Gallery.posted_at.desc().nullslast(), Gallery.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "group_id": str(version.group_id),
        "versions": [
            {
                "id": item.id,
                "source": item.source,
                "source_id": item.source_id,
                "title": item.title,
                "posted_at": item.posted_at,
            }
            for item in rows
        ],
    }


@router.post("/galleries/{gallery_id}/versions")
async def link_version(
    gallery_id: int, body: VersionCreate, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)
):
    origin = await _gallery(db, gallery_id, auth)
    target = await _gallery(db, body.gallery_id, auth)
    await _require_write(db, origin, auth)
    await _require_write(db, target, auth)
    origin_version = await db.get(GalleryVersion, origin.id)
    target_version = await db.get(GalleryVersion, target.id)
    group_id = (
        origin_version.group_id if origin_version else target_version.group_id if target_version else str(uuid.uuid4())
    )
    if origin_version and target_version and origin_version.group_id != target_version.group_id:
        await db.execute(
            update(GalleryVersion).where(GalleryVersion.group_id == target_version.group_id).values(group_id=group_id)
        )
    for item, current in ((origin, origin_version), (target, target_version)):
        if current is None:
            db.add(GalleryVersion(gallery_id=item.id, group_id=group_id, linked_by_user_id=auth["user_id"]))
    await db.commit()
    return {"status": "ok", "group_id": str(group_id)}
