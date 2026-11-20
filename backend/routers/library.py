"""Local library CRUD — queries galleries/images tables via GIN index.

The route handlers live in the ``routers/library_*.py`` sub-routers; this module
aggregates them in the original registration order (static ``/galleries/...``
paths must stay ahead of ``/galleries/{source}/{source_id}...``).
"""

from fastapi import APIRouter

from core.gallery_helpers import build_cover_map
from services.library_helpers import encode_cursor as _encode_cursor
from services.library_helpers import single_cover_thumb as _single_cover_thumb
from services.library_helpers import user_gallery_state as _user_gallery_state

from . import (
    library_artists,
    library_batch,
    library_excluded,
    library_files,
    library_galleries_list,
    library_galleries_meta,
    library_gallery_detail,
    library_gallery_edit,
    library_images_browse,
    library_images_hide,
    library_reading,
    library_similar,
    library_trash_actions,
    library_trash_list,
)

router = APIRouter(tags=["library"])

_build_cover_map = build_cover_map

for _sub in (
    library_galleries_meta,
    library_galleries_list,
    library_images_browse,
    library_artists,
    library_files,
    library_batch,
    library_trash_list,
    library_trash_actions,
    library_gallery_detail,
    library_gallery_edit,
    library_images_hide,
    library_reading,
    library_similar,
    library_excluded,
):
    router.include_router(_sub.router)

__all__ = [
    "router",
    "_build_cover_map",
    "_encode_cursor",
    "_single_cover_thumb",
    "_user_gallery_state",
]
