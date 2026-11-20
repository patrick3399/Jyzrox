"""Explorer operation status and merge endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import (
    WorkbenchOperation,
)
from services.explorer_requests import (
    MergeRequest,
)

router = APIRouter()
_member = require_role("member")


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: uuid.UUID,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    operation = await db.get(WorkbenchOperation, operation_id)
    if operation is None or (auth["role"] != "admin" and operation.user_id != auth["user_id"]):
        raise HTTPException(status_code=404, detail="Workbench operation not found")
    return {
        "id": str(operation.id),
        "kind": operation.kind,
        "status": operation.status,
        "selection_count": operation.selection_count,
        "progress": operation.progress,
        "error": operation.error,
        "created_at": operation.created_at,
        "started_at": operation.started_at,
        "finished_at": operation.finished_at,
    }


@router.post("/merge/preview")
async def preview_merge(
    request: MergeRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Return conflicts and image dedup effects without mutating galleries."""
    from services.workbench_merge import preview_gallery_merge

    return await preview_gallery_merge(db, request.gallery_ids, request.target_id, auth)


@router.post("/merge")
async def merge_galleries(
    request: MergeRequest,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Copy source references into the target and move sources to Trash."""
    from datetime import UTC, datetime

    from core.audit import log_audit
    from services.workbench_merge import execute_gallery_merge

    operation = WorkbenchOperation(
        id=uuid.uuid4(),
        user_id=auth["user_id"],
        kind="merge",
        status="running",
        selection_count=len(set(request.gallery_ids)),
        params={
            "gallery_ids": request.gallery_ids,
            "target_id": request.target_id,
            "scalar_sources": request.scalar_sources,
            "source_routes": "404",
        },
        started_at=datetime.now(UTC),
    )
    db.add(operation)
    result = await execute_gallery_merge(
        db,
        request.gallery_ids,
        request.target_id,
        request.scalar_sources,
        auth,
        operation.id,
    )
    operation.status = "completed"
    operation.progress = result
    operation.finished_at = datetime.now(UTC)
    await db.commit()

    await emit_safe(
        EventType.GALLERY_BATCH_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="workbench_operation",
        resource_id=str(operation.id),
        action="merge",
        **result,
    )
    await log_audit(
        auth["user_id"],
        "gallery.merge",
        f"target={result['target_id']} sources={result['source_ids']} source_routes=404",
    )
    return {"operation_id": str(operation.id), "status": operation.status, **result}
