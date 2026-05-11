"""Admin endpoints for database backup artifacts."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

import core.queue
from core.auth import require_role
from core.config import settings

router = APIRouter(tags=["backups"])
_admin = require_role("admin")


def _backup_dir() -> Path:
    return Path(settings.data_backups_path)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _backup_record(manifest_path: Path, data: dict[str, Any]) -> dict[str, Any]:
    filename = data.get("filename")
    safe_filename = str(filename) if filename and Path(str(filename)).name == str(filename) else None
    dump_path = manifest_path.parent / safe_filename if safe_filename else None
    exists = bool(dump_path and dump_path.exists())
    size_bytes = data.get("size_bytes")
    if exists and not isinstance(size_bytes, int):
        try:
            size_bytes = dump_path.stat().st_size
        except OSError:
            size_bytes = None
    return {
        "id": data.get("id") or manifest_path.stem,
        "status": data.get("status") or "unknown",
        "created_at": data.get("created_at"),
        "filename": safe_filename,
        "manifest": manifest_path.name,
        "size_bytes": size_bytes,
        "sha256": data.get("sha256"),
        "app_version": data.get("app_version"),
        "database": data.get("database"),
        "exists": exists,
        "error": data.get("error"),
    }


@router.get("")
@router.get("/")
async def list_backups(_: dict = Depends(_admin)):
    backup_dir = _backup_dir()
    if not backup_dir.exists():
        return {"backups": [], "path": str(backup_dir)}

    records = []
    for manifest_path in backup_dir.glob("jyzrox_db_*.json"):
        data = _load_manifest(manifest_path)
        if data is not None:
            records.append(_backup_record(manifest_path, data))
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"backups": records, "path": str(backup_dir)}


@router.post("/run")
async def run_backup(_: dict = Depends(_admin)):
    await core.queue.enqueue(
        "database_backup_job",
        force=True,
        _timeout=settings.backup_pg_dump_timeout,
        _job_id="manual:database_backup",
    )
    return {"status": "queued", "job": "database_backup_job"}


@router.get("/{backup_id}/download")
async def download_backup(backup_id: str, _: dict = Depends(_admin)):
    if "/" in backup_id or "\\" in backup_id or backup_id in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid backup id")
    backup_dir = _backup_dir()
    manifest_path = backup_dir / f"{backup_id}.json"
    data = _load_manifest(manifest_path)
    if data is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    filename = data.get("filename")
    safe_filename = str(filename) if filename and Path(str(filename)).name == str(filename) else None
    if not safe_filename:
        raise HTTPException(status_code=404, detail="Backup file not found")
    dump_path = backup_dir / safe_filename
    if not dump_path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return FileResponse(
        dump_path,
        filename=safe_filename,
        media_type="application/gzip",
    )


@router.delete("/{backup_id}")
async def delete_backup(backup_id: str, _: dict = Depends(_admin)):
    if "/" in backup_id or "\\" in backup_id or backup_id in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid backup id")
    backup_dir = _backup_dir()
    manifest_path = backup_dir / f"{backup_id}.json"
    data = _load_manifest(manifest_path)
    if data is None:
        raise HTTPException(status_code=404, detail="Backup not found")

    deleted = []
    filename = data.get("filename")
    safe_filename = str(filename) if filename and Path(str(filename)).name == str(filename) else None
    for path in [backup_dir / safe_filename if safe_filename else None, manifest_path]:
        if path is None:
            continue
        try:
            if path.exists():
                path.unlink()
                deleted.append(path.name)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "deleted": deleted}
