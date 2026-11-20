"""Explorer bulk metadata edit and delete endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    DownloadJob,
    WorkbenchOperation,
)
from services.explorer_requests import (
    BulkDeleteRequest,
    BulkMetadataRequest,
)
from services.explorer_requests import (
    resolve_bulk_selection as _resolve_bulk_selection,
)
from services.gallery_lifecycle import mark_trashed
from services.workbench_metadata import (
    apply_manual_scalar_changes,
    load_writable_galleries,
)

router = APIRouter()
_member = require_role("member")


@router.post("/operations/metadata")
async def bulk_edit_metadata(
    request: BulkMetadataRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Apply explicit tri-state scalar edits and record one durable operation."""
    effective = {name: (change.mode, change.value) for name, change in request.fields.items() if change.mode != "keep"}
    if not effective:
        raise HTTPException(status_code=400, detail="No metadata changes were requested")

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="metadata",
        status="running",
        selection_count=len(galleries),
        params={
            "gallery_ids": [gallery.id for gallery in galleries],
            "fields": {name: {"mode": mode, "value": value} for name, (mode, value) in effective.items()},
            "lock_fields": request.lock_fields,
        },
    )
    db.add(operation)
    changed_count = await apply_manual_scalar_changes(
        db,
        galleries,
        effective,
        actor_user_id=auth["user_id"],
        operation_id=operation.id,
        lock_fields=request.lock_fields,
    )
    operation.status = "completed"
    operation.progress = {"processed": len(galleries), "changed_fields": changed_count}
    from datetime import UTC, datetime

    operation.started_at = operation.created_at or datetime.now(UTC)
    operation.finished_at = datetime.now(UTC)
    await db.commit()

    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        gallery_ids=[gallery.id for gallery in galleries],
        action="metadata",
    )
    return {
        "operation_id": str(operation.id),
        "status": operation.status,
        "selection_count": len(galleries),
        "changed_fields": changed_count,
    }


@router.post("/operations/delete")
async def bulk_delete_galleries(
    request: BulkDeleteRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Move an explicit or query-wide Gallery selection to Trash."""
    from datetime import UTC, datetime

    gallery_ids = await _resolve_bulk_selection(request, auth)
    if not gallery_ids:
        raise HTTPException(status_code=400, detail="The selection is empty")
    galleries = await load_writable_galleries(db, gallery_ids, auth, lock_rows=True)
    active_ids = set(
        (
            await db.execute(
                select(DownloadJob.gallery_id).where(
                    DownloadJob.gallery_id.in_(gallery_ids),
                    DownloadJob.status.in_(("queued", "running", "paused")),
                )
            )
        ).scalars()
    )
    now = datetime.now(UTC)
    affected = [gallery for gallery in galleries if gallery.id not in active_ids]
    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="delete",
        status="completed",
        selection_count=len(galleries),
        params={"gallery_ids": gallery_ids, "destination": "trash"},
        progress={"affected": len(affected), "skipped_active_downloads": sorted(active_ids)},
        started_at=now,
        finished_at=now,
    )
    db.add(operation)
    mark_trashed(affected, reason="user", actor_user_id=auth["user_id"], now=now)
    await db.commit()
    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action="delete",
        gallery_ids=[gallery.id for gallery in affected],
    )
    return {
        "operation_id": str(operation.id),
        "status": "completed",
        "affected": len(affected),
        "skipped_active_downloads": sorted(active_ids),
    }
