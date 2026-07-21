"""LoRA artifact library and ComfyUI generated-image import."""

import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_role
from core.config import settings
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import Dataset, Gallery, GeneratedImageMetadata, Image, LoraModel
from services.cas import create_library_symlink, increment_ref_count, store_blob

router = APIRouter(tags=["training-assets"])
_member = require_role("member")
_LORA_MAX_BYTES = 20 * 1024 * 1024 * 1024
_PNG_MAX_BYTES = 200 * 1024 * 1024


def _parse_json_object(value: str, field: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f"{field} must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field} must be a JSON object")
    return parsed


def _parse_trigger_words(value: str) -> list[str]:
    words = [item.strip() for item in value.split(",") if item.strip()]
    return list(dict.fromkeys(words))[:100]


async def _write_upload(upload: UploadFile, path: Path, limit: int) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    digest = hashlib.sha256()
    try:
        with path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail="Uploaded file is too large")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def _serialize_lora(model: LoraModel) -> dict:
    return {
        "id": model.id,
        "dataset_id": model.dataset_id,
        "name": model.name,
        "file_size": model.file_size,
        "sha256": model.sha256,
        "trigger_words": model.trigger_words or [],
        "training_params": model.training_params or {},
        "created_at": model.created_at.isoformat() if model.created_at else None,
    }


@router.get("/loras")
async def list_loras(auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)):
    rows = (
        (
            await db.execute(
                select(LoraModel)
                .where(LoraModel.user_id == auth["user_id"])
                .order_by(LoraModel.created_at.desc(), LoraModel.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"loras": [_serialize_lora(row) for row in rows]}


@router.post("/loras", status_code=201)
async def upload_lora(
    name: str = Form(..., min_length=1, max_length=200),
    dataset_id: int | None = Form(default=None),
    trigger_words: str = Form(default=""),
    training_params: str = Form(default="{}"),
    file: UploadFile = File(...),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    if Path(file.filename or "").suffix.lower() != ".safetensors":
        raise HTTPException(status_code=400, detail="LoRA file must use the .safetensors extension")
    if dataset_id is not None:
        owned = (
            await db.execute(select(Dataset.id).where(Dataset.id == dataset_id, Dataset.user_id == auth["user_id"]))
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(status_code=404, detail="Dataset not found")

    parsed_training_params = _parse_json_object(training_params, "training_params")
    parsed_trigger_words = _parse_trigger_words(trigger_words)

    root = Path(settings.data_training_path) / "loras" / str(auth["user_id"])
    token = uuid.uuid4().hex
    temporary = root / f".{token}.upload"
    destination = root / f"{token}.safetensors"
    size, sha256 = await _write_upload(file, temporary, _LORA_MAX_BYTES)
    os.replace(temporary, destination)
    model = LoraModel(
        user_id=auth["user_id"],
        dataset_id=dataset_id,
        name=name.strip(),
        file_path=str(destination),
        file_size=size,
        sha256=sha256,
        trigger_words=parsed_trigger_words,
        training_params=parsed_training_params,
    )
    db.add(model)
    try:
        await db.commit()
        await db.refresh(model)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return _serialize_lora(model)


@router.get("/loras/{model_id}/file")
async def download_lora(model_id: int, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)):
    model = (
        await db.execute(select(LoraModel).where(LoraModel.id == model_id, LoraModel.user_id == auth["user_id"]))
    ).scalar_one_or_none()
    if model is None or not Path(model.file_path).is_file():
        raise HTTPException(status_code=404, detail="LoRA model not found")
    return FileResponse(model.file_path, filename=f"{model.name}.safetensors")


@router.delete("/loras/{model_id}")
async def delete_lora(model_id: int, auth: dict = Depends(_member), db: AsyncSession = Depends(get_db)):
    model = (
        await db.execute(select(LoraModel).where(LoraModel.id == model_id, LoraModel.user_id == auth["user_id"]))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="LoRA model not found")
    path = Path(model.file_path)
    await db.delete(model)
    await db.commit()
    path.unlink(missing_ok=True)
    return {"status": "ok"}


def _read_comfy_metadata(path: Path) -> tuple[int, int, dict | None, dict | None]:
    with PILImage.open(path) as image:
        if image.format != "PNG":
            raise ValueError("ComfyUI import requires a PNG image")
        image.verify()
    with PILImage.open(path) as image:
        width, height = image.size
        info = dict(image.info)

    def parse(value: object) -> dict | None:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except json.JSONDecodeError:
                return {"raw": value}
        return None

    return width, height, parse(info.get("prompt")), parse(info.get("workflow"))


@router.post("/comfyui/import", status_code=201)
async def import_comfyui_png(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=500),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    if Path(file.filename or "").suffix.lower() != ".png":
        raise HTTPException(status_code=400, detail="ComfyUI import requires a PNG file")
    temp = Path(settings.data_training_path) / "imports" / f".{uuid.uuid4().hex}.png"
    _, sha256 = await _write_upload(file, temp, _PNG_MAX_BYTES)
    try:
        width, height, prompt_json, workflow_json = await asyncio.to_thread(_read_comfy_metadata, temp)
        source_id = f"{auth['user_id']}:{sha256}"
        existing = (
            await db.execute(select(Gallery).where(Gallery.source == "comfyui", Gallery.source_id == source_id))
        ).scalar_one_or_none()
        if existing is not None:
            return {"status": "exists", "gallery_id": existing.id, "source_id": source_id}

        blob = await store_blob(temp, sha256, db)
        blob.width = width
        blob.height = height
        gallery = Gallery(
            source="comfyui",
            source_id=source_id,
            title=(title or "").strip() or f"ComfyUI {sha256[:12]}",
            pages=1,
            download_status="complete",
            import_mode="copy",
            created_by_user_id=auth["user_id"],
            visibility="private",
        )
        db.add(gallery)
        await db.flush()
        image = Image(
            gallery_id=gallery.id,
            page_num=1,
            filename="generated.png",
            blob_sha256=sha256,
            visibility="active",
            source_item_id=f"comfyui:{sha256}",
        )
        db.add(image)
        await db.flush()
        db.add(
            GeneratedImageMetadata(
                image_id=image.id,
                prompt_json=prompt_json,
                workflow_json=workflow_json,
            )
        )
        await increment_ref_count(sha256, db)
        await db.commit()
        await create_library_symlink("comfyui", source_id, "generated.png", blob)
        await emit_safe(
            EventType.GALLERY_DISCOVERED,
            actor_user_id=auth["user_id"],
            resource_type="gallery",
            resource_id=gallery.id,
            source="comfyui",
        )
        return {
            "status": "imported",
            "gallery_id": gallery.id,
            "image_id": image.id,
            "source_id": source_id,
            "has_prompt": prompt_json is not None,
            "has_workflow": workflow_json is not None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    finally:
        temp.unlink(missing_ok=True)


@router.get("/comfyui/images/{image_id}/metadata")
async def get_comfyui_metadata(
    image_id: int,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(GeneratedImageMetadata)
            .join(Image, Image.id == GeneratedImageMetadata.image_id)
            .join(Gallery, Gallery.id == Image.gallery_id)
            .where(Image.id == image_id, gallery_access_filter(auth))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Generated image metadata not found")
    return {
        "image_id": image_id,
        "prompt": row.prompt_json,
        "workflow": row.workflow_json,
        "imported_at": row.imported_at.isoformat() if row.imported_at else None,
    }
