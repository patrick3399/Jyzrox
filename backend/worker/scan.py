"""Library scan and rescan jobs for the worker package.

The jobs live in ``worker.scan_*`` modules; this module re-exports the names
that ``worker/__init__.py`` and tests import. Patch a global in the module
that looks it up, not here.
"""

from worker.scan_common import _discover_single_library_dir, _ImportRequest, _LibrarySpec
from worker.scan_discover import (
    auto_discover_job,
    rescan_library_path_job,
    scheduled_scan_job,
    sync_all_link_galleries,
)
from worker.scan_move import move_library_path_job
from worker.scan_paths import reconcile_library_path_job, rescan_by_path_job
from worker.scan_rescan_gallery import rescan_gallery_job
from worker.scan_rescan_library import rescan_library_job
from worker.scan_vanished import VANISHED_LINK_GALLERY_GRACE, _hold_vanished_link_gallery

__all__ = [
    "VANISHED_LINK_GALLERY_GRACE",
    "_ImportRequest",
    "_LibrarySpec",
    "_discover_single_library_dir",
    "_hold_vanished_link_gallery",
    "auto_discover_job",
    "move_library_path_job",
    "reconcile_library_path_job",
    "rescan_by_path_job",
    "rescan_gallery_job",
    "rescan_library_job",
    "rescan_library_path_job",
    "scheduled_scan_job",
    "sync_all_link_galleries",
]
