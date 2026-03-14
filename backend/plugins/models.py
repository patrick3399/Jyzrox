"""Plugin system Pydantic models."""

from __future__ import annotations

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


class PluginMeta(BaseModel):
    name: str
    source_id: str
    version: str
    description: str = ""
    url_patterns: list[str]
    credential_schema: list[FieldDef]
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
    failed_pages: list[int] = []
    error: str | None = None


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
