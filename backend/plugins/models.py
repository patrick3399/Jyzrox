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


class PluginMeta(BaseModel):
    name: str
    source_id: str
    version: str
    url_patterns: list[str]
    credential_schema: list[FieldDef]
    concurrency: int = 1


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
    status: Literal["done", "cancelled", "failed"]
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
