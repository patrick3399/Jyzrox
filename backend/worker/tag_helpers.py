"""Backward-compatible re-export shim.

The implementation moved to ``services.tag_helpers`` so both routers and
worker jobs can import shared tag logic from a single, boundary-compliant
location. This module is kept only because ``worker/importer.py`` still
imports from it directly; new code should import from ``services.tag_helpers``
instead.
"""

from services.tag_helpers import (  # noqa: F401
    clear_ai_tags,
    parse_tag_strings,
    rebuild_gallery_tags_array,
    rebuild_tag_counts,
    upsert_tag_translations,
)

__all__ = [
    "clear_ai_tags",
    "parse_tag_strings",
    "rebuild_gallery_tags_array",
    "rebuild_tag_counts",
    "upsert_tag_translations",
]
