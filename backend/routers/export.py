"""Training Data Export (Kohya format)."""

import os
import zipfile
from io import BytesIO
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from core.database import async_session
from sqlalchemy import text
from typing import List

router = APIRouter(tags=["export"])

@router.get("/kohya/{gallery_id}")
async def export_kohya(gallery_id: int):
    """Generates a zip file containing images and corresponding .txt files with tags."""
    
    async with async_session() as session:
        # Get Gallery Tags
        g_result = await session.execute(
            text("SELECT tags_array FROM galleries WHERE id = :gid"),
            {"gid": gallery_id}
        )
        g_row = g_result.fetchone()
        if not g_row:
            raise HTTPException(status_code=404, detail="Gallery not found")
            
        gallery_tags = g_row.tags_array or []

        # Get Images
        i_result = await session.execute(
            text("SELECT id, filename, file_path, tags_array FROM images WHERE gallery_id = :gid ORDER BY page_num"),
            {"gid": gallery_id}
        )
        images = i_result.fetchall()

    if not images:
        raise HTTPException(status_code=404, detail="No images found in gallery")

    # Create Zip in memory
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for img in images:
            if not img.file_path or not os.path.exists(img.file_path):
                continue
                
            # Add image file to zip
            zip_file.write(img.file_path, arcname=img.filename)
            
            # Combine gallery tags and specific image tags
            all_tags = set(gallery_tags)
            if img.tags_array:
                all_tags.update(img.tags_array)
                
            # Create tag text file
            txt_filename = os.path.splitext(img.filename)[0] + ".txt"
            tag_string = ", ".join(all_tags)
            
            zip_file.writestr(txt_filename, tag_string)

    zip_buffer.seek(0)
    
    return StreamingResponse(
        iter([zip_buffer.getvalue()]), 
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=gallery_{gallery_id}_kohya.zip"}
    )
