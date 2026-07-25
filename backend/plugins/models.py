"""Plugin system Pydantic models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FieldDef(BaseModel):
    name: str
    field_type: Literal["text", "password", "textarea", "select"]
    label: str
    required: bool = False
    placeholder: str = ""


class SiteInfo(BaseModel):
    domain: str
    name: str
    source_id: str
    category: str
    has_tags: bool = False


class OAuthConfig(BaseModel):
    auth_url_endpoint: str
    callback_endpoint: str
    display_name: str


class CredentialFlow(BaseModel):
    flow_type: Literal["fields", "oauth", "login"]
    fields: list[FieldDef] = []
    oauth_config: OAuthConfig | None = None
    login_endpoint: str | None = None
    verify_endpoint: str | None = None


class CredentialStatus(BaseModel):
    valid: bool
    username: str | None = None
    error: str | None = None
    expires_at: datetime | None = None


class GalleryImportData(BaseModel):
    source: str
    source_id: str
    title: str
    title_jpn: str = ""
    category: str = ""
    language: str = ""
    tags: list[str] = []
    artist_id: str | None = None
    page_count: int = 0
    posted_at: datetime | None = None
    uploader: str = ""
    extra: dict = {}


class NewWork(BaseModel):
    url: str
    title: str = ""
    source_id: str = ""
    thumbnail_url: str | None = None
    posted_at: datetime | None = None


class DiscoveredWorks(BaseModel):
    """Result of a subscription discovery pass (Subscribable capability).

    latest_id is the new boundary independent of per-subscription policy, so a
    filtered subscription can advance past skipped items; None means keep the
    previous boundary. job_options are merged into every enqueued job's options.
    """

    works: list[NewWork] = []
    latest_id: str | None = None
    job_options: dict = {}


class PreviewData(BaseModel):
    """Metadata preview for a URL before downloading (Previewable capability)."""

    source: str
    title: str | None = None
    pages: int | None = None
    tags: list[str] | None = None
    uploader: str | None = None
    rating: float | None = None
    thumb_url: str | None = None
    category: str | None = None


class RemoteMetadataResult(BaseModel):
    """Result of fetching fresh source metadata (Refreshable capability).

    scalar_values keys must be understood by
    services.workbench_metadata.apply_source_scalar_metadata; tags=None means
    the source provides no tag data (do not touch tags).
    """

    status: Literal["ok", "expunged", "skipped", "error"] = "ok"
    reason: str | None = None
    scalar_values: dict = {}
    tags: list[str] | None = None


class PluginMeta(BaseModel):
    name: str
    source_id: str
    version: str
    description: str = ""
    url_patterns: list[str] = []
    credential_schema: list[FieldDef] = []
    supported_sites: list[SiteInfo] = []
    concurrency: int = 1
    semaphore_key: str | None = None
    needs_all_credentials: bool = False


class GalleryMetadata(BaseModel):
    source: str
    source_id: str
    title: str
    tags: list[str] = []
    pages: int = 0
    uploader: str = ""
    posted_at: datetime | None = None
    extra: dict = {}


class DownloadResult(BaseModel):
    status: Literal["done", "cancelled", "failed", "partial"]
    downloaded: int
    total: int
    # Pages this run actually obtained. `downloaded` counts what the gallery
    # holds afterwards, which for an incremental repair includes pages that were
    # skipped without a fetch — so it cannot answer "did this run make
    # progress". None means the plugin does not draw the distinction, in which
    # case callers fall back to `downloaded`.
    fetched: int | None = None
    failed_pages: list[int] = []
    error: str | None = None
    unsupported_urls: list[str] = []
    error_urls: list[str] = []


class SearchResult(BaseModel):
    galleries: list[dict]
    total: int
    page: int = 0
    has_next: bool = False
    has_prev: bool = False
    next_cursor: str | None = None
    prev_cursor: str | None = None
    extra: dict = {}


class BrowseSchema(BaseModel):
    search_fields: list[FieldDef]
    supports_favorites: bool = False
    supports_popular: bool = False
    supports_toplist: bool = False


class TagResult(BaseModel):
    image_path: str
    tags: list[str]
    confidence: list[float] = []


class ProcessResult(BaseModel):
    status: Literal["done", "failed"]
    output_path: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict = {}
    error: str | None = None


class ServiceHealth(BaseModel):
    online: bool
    service: str
    version: str | None = None
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    models: list[str] = []
    error: str | None = None
