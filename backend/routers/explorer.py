"""Library Workbench APIs for navigation, bulk metadata, and merge."""

from fastapi import APIRouter

from routers import (
    explorer_actions,
    explorer_galleries,
    explorer_merge,
    explorer_metadata_ops,
    explorer_nav,
    explorer_physical,
    explorer_roots,
)

router = APIRouter(tags=["explorer"])

router.include_router(explorer_nav.router)
router.include_router(explorer_roots.router)
router.include_router(explorer_physical.router)
router.include_router(explorer_metadata_ops.router)
router.include_router(explorer_actions.router)
router.include_router(explorer_merge.router)
router.include_router(explorer_galleries.router)
