"""Abstract base classes for the Jyzrox plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path

from plugins.models import (
    BrowseSchema,
    DownloadResult,
    GalleryMetadata,
    PluginMeta,
    SearchResult,
    TagResult,
)


class SourcePlugin(ABC):
    """Plugin that can download galleries from a specific source."""

    meta: PluginMeta

    @abstractmethod
    async def can_handle(self, url: str) -> bool:
        """Return True if this plugin can handle the given URL."""
        ...

    @abstractmethod
    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> DownloadResult:
        """Download a gallery to dest_dir. Returns a DownloadResult."""
        ...

    @abstractmethod
    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        """Parse gallery metadata from a downloaded directory."""
        ...


class BrowsePlugin(ABC):
    """Plugin that supports browsing/searching a remote source."""

    meta: PluginMeta

    @abstractmethod
    def browse_schema(self) -> BrowseSchema:
        """Describe the search fields and capabilities of this browse plugin."""
        ...

    @abstractmethod
    async def search(
        self,
        params: dict,
        credentials: dict | None = None,
    ) -> SearchResult:
        """Perform a search and return results."""
        ...

    @abstractmethod
    async def proxy_image(
        self,
        url: str,
        credentials: dict | None = None,
    ) -> tuple[bytes, str]:
        """Fetch image bytes and content-type for proxying."""
        ...


class TaggerPlugin(ABC):
    """Plugin that tags images using AI/ML models."""

    meta: PluginMeta

    @abstractmethod
    async def tag_images(self, image_paths: list[Path]) -> list[TagResult]:
        """Tag a list of images, returning one TagResult per image."""
        ...
