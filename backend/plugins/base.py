"""Abstract base classes and Protocol interfaces for the Jyzrox plugin system."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from fastapi import APIRouter

from plugins.models import (
    BrowseSchema,
    CredentialFlow,
    CredentialStatus,
    DiscoveredWorks,
    DownloadResult,
    GalleryImportData,
    GalleryMetadata,
    PluginMeta,
    PreviewData,
    RemoteMetadataResult,
    SearchResult,
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
        on_file: Callable[[Path, str | None], Awaitable[None]] | None = None,
        options: dict | None = None,
    ) -> DownloadResult: ...

    def resolve_output_dir(self, url: str, base_path: Path, job_id: str | None = None) -> Path: ...

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
class CredentialProvider(Protocol):
    meta: PluginMeta

    def credential_flows(self) -> list[CredentialFlow]: ...

    async def verify_credential(self, credentials: dict) -> CredentialStatus: ...


@runtime_checkable
class Previewable(Protocol):
    meta: PluginMeta

    async def preview_url(self, url: str) -> PreviewData | None: ...


@runtime_checkable
class Refreshable(Protocol):
    meta: PluginMeta

    async def fetch_remote_metadata(self, source_id: str, source_url: str | None) -> RemoteMetadataResult: ...


@runtime_checkable
class Subscribable(Protocol):
    """Incremental subscription discovery.

    Plugins that register this capability get per-work incremental checks from
    the subscription worker; sources without it fall back to enqueueing the
    subscription URL as one archive-refresh download job (risk #8).
    """

    meta: PluginMeta

    def subscription_identity(self, url: str) -> str | None: ...

    async def discover_new_works(
        self,
        url: str,
        last_known: str | None,
        options: dict,
        credentials: dict | str | None,
    ) -> DiscoveredWorks: ...


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
        on_file: Callable[[Path, str | None], Awaitable[None]] | None = None,
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
