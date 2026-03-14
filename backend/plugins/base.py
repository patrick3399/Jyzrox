"""Abstract base classes and Protocol interfaces for the Jyzrox plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from fastapi import APIRouter

from plugins.models import (
    BrowseSchema,
    CredentialFlow,
    CredentialStatus,
    DownloadResult,
    GalleryImportData,
    GalleryMetadata,
    NewWork,
    PluginMeta,
    SearchResult,
    TagResult,
)


# ---------------------------------------------------------------------------
# Protocol interfaces (Phase 2)
# ---------------------------------------------------------------------------

@runtime_checkable
class HasMeta(Protocol):
    meta: PluginMeta


@runtime_checkable
class Downloadable(Protocol):
    meta: PluginMeta

    async def can_handle(self, url: str) -> bool: ...

    async def download(
        self,
        url: str,
        dest_dir: Path,
        credentials: dict | None,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        cancel_check: Callable[[], Awaitable[bool]] | None = None,
        pid_callback: Callable[[int], Awaitable[None]] | None = None,
        pause_check: Callable[[], Awaitable[bool]] | None = None,
        on_file: Callable[[Path], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult: ...

    def resolve_output_dir(self, url: str, base_path: Path) -> Path: ...

    def requires_credentials(self) -> bool: ...

    async def resolve_metadata(
        self,
        url: str,
        credentials: dict | str | None,
    ) -> GalleryImportData | None: ...


@runtime_checkable
class Browsable(Protocol):
    meta: PluginMeta

    def get_browse_router(self) -> APIRouter: ...


@runtime_checkable
class Parseable(Protocol):
    meta: PluginMeta

    def parse_import(self, dest_dir: Path, raw_meta: dict | None) -> GalleryImportData: ...


@runtime_checkable
class Subscribable(Protocol):
    meta: PluginMeta

    async def check_new_works(
        self,
        artist_id: str,
        last_known: str | None,
        credentials: dict | None,
    ) -> list[NewWork]: ...


@runtime_checkable
class CredentialProvider(Protocol):
    meta: PluginMeta

    def credential_flows(self) -> list[CredentialFlow]: ...

    async def verify_credential(self, credentials: dict) -> CredentialStatus: ...


@runtime_checkable
class Taggable(Protocol):
    meta: PluginMeta

    async def tag_images(self, image_paths: list[Path]) -> list[TagResult]: ...


# ---------------------------------------------------------------------------
# Legacy ABCs — DEPRECATED — use Protocol interfaces above
# ---------------------------------------------------------------------------

class SourcePlugin(ABC):
    """Plugin that can download galleries from a specific source.

    # DEPRECATED — use Protocol interfaces above
    """

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
        pause_check: Callable[[], Awaitable[bool]] | None = None,
        on_file: Callable[[Path], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult:
        """Download a gallery to dest_dir. Returns a DownloadResult."""
        ...

    @abstractmethod
    def parse_metadata(self, dest_dir: Path) -> GalleryMetadata | None:
        """Parse gallery metadata from a downloaded directory."""
        ...

    async def resolve_metadata(
        self,
        url: str,
        credentials: dict | str | None,
    ) -> GalleryImportData | None:
        """Pre-download metadata resolution. Override in subclasses."""
        return None


class BrowsePlugin(ABC):
    """Plugin that supports browsing/searching a remote source.

    # DEPRECATED — use Protocol interfaces above
    """

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
    """Plugin that tags images using AI/ML models.

    # DEPRECATED — use Protocol interfaces above
    """

    meta: PluginMeta

    @abstractmethod
    async def tag_images(self, image_paths: list[Path]) -> list[TagResult]:
        """Tag a list of images, returning one TagResult per image."""
        ...
