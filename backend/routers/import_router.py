"""Gallery import handling (Link and Copy modes)."""

from fastapi import APIRouter

from services.media_formats import MEDIA_EXTENSIONS as _SUPPORTED_EXTS

from . import import_batch, import_browse, import_conflicts, import_libraries, import_rescan, import_webclip

router = APIRouter(tags=["import"])

router.include_router(import_webclip.router)
router.include_router(import_batch.router)
router.include_router(import_conflicts.router)
router.include_router(import_browse.router)
router.include_router(import_rescan.router)
router.include_router(import_libraries.router)

__all__ = ["_SUPPORTED_EXTS", "router"]
