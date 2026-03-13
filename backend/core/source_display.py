"""Per-source display configuration for cover selection and image ordering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class SourceDisplayConfig:
    """Display preferences for a given source."""

    image_order: Literal["asc", "desc"] = "asc"
    cover_page: Literal["first", "last"] = "first"


_DEFAULT = SourceDisplayConfig()


def get_display_config(source: str) -> SourceDisplayConfig:
    """Return display config for the given source.

    Checks gallery-dl site registry first; falls back to default for
    EH, Pixiv, local, and unknown sources.
    """
    from plugins.builtin.gallery_dl._sites import get_site_config

    cfg = get_site_config(source)
    if cfg:
        return SourceDisplayConfig(
            image_order=cfg.image_order,
            cover_page=cfg.cover_page,
        )
    return _DEFAULT
