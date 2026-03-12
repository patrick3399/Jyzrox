"""Training Data Export (Kohya format)."""

import os
import zipfile
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from core.auth import require_auth, require_role
from core.database import async_session
from db.models import Gallery, Image
from services.cas import resolve_blob_path

router = APIRouter(tags=["export"])

_member = require_role("member")


@router.get("/kohya/{gallery_id}")
async def export_kohya(gallery_id: int, auth: dict = Depends(_member)):
    """Generates a zip file containing images and corresponding .txt files with tags."""

    async with async_session() as session:
        # Get Gallery
        gallery = await session.get(Gallery, gallery_id)
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        # Ownership check: admin can export any gallery; members only their own or unowned
        if auth["role"] != "admin":
            if gallery.created_by_user_id is not None and gallery.created_by_user_id != auth["user_id"]:
                raise HTTPException(status_code=403, detail="You do not have permission to export this gallery")

        gallery_tags = gallery.tags_array or []

        # Get Images with blobs eagerly loaded
        images = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .order_by(Image.page_num)
                .options(selectinload(Image.blob))
            )
        ).scalars().all()

    if not images:
        raise HTTPException(status_code=404, detail="No images found in gallery")

    # Resolve filesystem paths via CAS
    def _file_path(img):
        if not img.blob:
            return None
        p = resolve_blob_path(img.blob)
        return p if p.exists() else None

    # Check total size before creating ZIP (limit: 2 GB)
    _MAX_ZIP_SIZE = 2 * 1024 * 1024 * 1024
    total_size = sum(
        img.blob.file_size for img in images if img.blob and img.blob.file_size
    )
    if total_size > _MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="Gallery too large to export (max 2 GB)")

    # Create Zip in memory
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i, img in enumerate(images):
            file_path = _file_path(img)
            if not file_path:
                continue

            # Use img.filename if available, otherwise fall back to a page-based name
            arcname = img.filename if img.filename else f"image_{i}"

            # Add image file to zip
            zip_file.write(str(file_path), arcname=arcname)

            # Combine gallery tags and specific image tags
            all_tags = set(gallery_tags)
            if img.tags_array:
                all_tags.update(img.tags_array)

            # Create tag text file
            base, _ = os.path.splitext(arcname)
            txt_filename = base + ".txt"
            tag_string = ", ".join(all_tags)

            zip_file.writestr(txt_filename, tag_string)

    zip_buffer.seek(0)

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=gallery_{gallery_id}_kohya.zip"},
    )
