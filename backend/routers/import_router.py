"""Gallery import handling (Link and Copy modes)."""

import os
import shutil
import hashlib
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional

from core.database import async_session
from core.auth import require_auth
from sqlalchemy import text
from core.config import settings

router = APIRouter(tags=["import"])

class ImportRequest(BaseModel):
    source_dir: str
    mode: str = "link" # "link" or "copy"
    metadata: Optional[dict] = None

def hash_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

async def process_import_task(req: ImportRequest, gallery_id: int):
    # This is a simplified version of the background worker logic for Phase 4
    src_path = Path(req.source_dir)
    if not src_path.exists() or not src_path.is_dir():
        return
    
    files = sorted([f for f in src_path.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg', '.png', '.mp4', '.gif', '.webm')])
    
    async with async_session() as session:
        for idx, f in enumerate(files):
            file_hash = hash_file(str(f))
            
            # check for duplicate
            dup_check = await session.execute(
                text("SELECT id FROM images WHERE file_hash = :fh LIMIT 1"),
                {"fh": file_hash}
            )
            dup_row = dup_check.fetchone()
            duplicate_of = dup_row.id if dup_row else None
            
            dest_path = str(f)
            if req.mode == "copy" and not duplicate_of:
                # copy to storage
                dest_dir = Path(settings.data_gallery_path) / "local" / str(gallery_id)
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = str(dest_dir / f.name)
                shutil.copy2(f, dest_path)
            
            media_type = "video" if f.suffix.lower() in ('.mp4', '.webm') else "gif" if f.suffix.lower() == '.gif' else "image"
            
            await session.execute(
                text("""
                    INSERT INTO images (gallery_id, page_num, filename, file_path, file_hash, media_type, duplicate_of)
                    VALUES (:gid, :pnum, :fname, :fpath, :fhash, :mtype, :dup)
                """),
                {
                    "gid": gallery_id,
                    "pnum": idx + 1,
                    "fname": f.name,
                    "fpath": dest_path,
                    "fhash": file_hash,
                    "mtype": media_type,
                    "dup": duplicate_of
                }
            )
        await session.commit()

@router.post("/")
async def start_import(
    req: ImportRequest,
    background_tasks: BackgroundTasks,
    _: dict = Depends(require_auth),
):
    if req.mode not in ("link", "copy"):
        raise HTTPException(status_code=400, detail="Invalid import mode")
    
    # Create DB entry
    async with async_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO galleries (source, source_id, title, import_mode) 
                VALUES ('local', :sid, :title, :mode) RETURNING id
            """),
            {
                "sid": os.path.basename(req.source_dir),
                "title": req.metadata.get("title", "Imported") if req.metadata else "Imported",
                "mode": req.mode
            }
        )
        gallery_id = result.scalar()
        await session.commit()
    
    background_tasks.add_task(process_import_task, req, gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}
