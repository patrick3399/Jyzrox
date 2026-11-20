"""Request models and selection helpers for the Library Workbench explorer routers."""

import json
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from core.redis_client import get_redis
from services.explorer_filesystem import (
    folder_stats_job_id,
)


class ScalarMutation(BaseModel):
    mode: Literal["keep", "set", "clear"] = "keep"
    value: Any | None = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.mode == "set" and self.value is None:
            raise ValueError("value is required when mode is set")
        return self


class BulkMetadataRequest(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    selection_token: str | None = None
    excluded_ids: list[int] = Field(default_factory=list, max_length=10_000)
    fields: dict[str, ScalarMutation] = Field(default_factory=dict, max_length=7)
    lock_fields: bool = True

    @model_validator(mode="after")
    def validate_selection(self):
        if bool(self.gallery_ids) == bool(self.selection_token):
            raise ValueError("Provide gallery_ids or selection_token, but not both")
        return self


class BulkDeleteRequest(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    selection_token: str | None = None
    excluded_ids: list[int] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_selection(self):
        if bool(self.gallery_ids) == bool(self.selection_token):
            raise ValueError("Provide gallery_ids or selection_token, but not both")
        return self


class BulkActionRequest(BulkDeleteRequest):
    action: Literal[
        "favorite",
        "unfavorite",
        "rate",
        "add_read_later",
        "remove_read_later",
        "add_collection",
        "remove_collection",
        "add_tags",
        "remove_tags",
    ]
    rating: int | None = Field(default=None, ge=0, le=5)
    collection_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=100)


class MergeRequest(BaseModel):
    gallery_ids: list[int] = Field(min_length=2, max_length=50)
    target_id: int
    scalar_sources: dict[str, int] = Field(default_factory=dict)


class ExplorerQueryRequest(BaseModel):
    node_kind: Literal["all", "source", "collection", "artist", "category", "saved_search", "smart", "trash"] = "all"
    node_id: str | None = None
    query: str = Field(default="", max_length=1000)
    sort: Literal["added_at", "content_updated_at", "posted_at", "title", "rating", "pages", "size"] = "added_at"
    direction: Literal["asc", "desc"] = "desc"
    category: str | None = Field(default=None, max_length=200)
    facets: bool = False
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=60, ge=1, le=200)


class CreateSelectionRequest(BaseModel):
    query: ExplorerQueryRequest


class PurgeImagesRequest(BaseModel):
    image_ids: list[int] | None = Field(default=None, max_length=1000)
    all_hidden: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_target(self):
        if bool(self.image_ids) == self.all_hidden:
            raise ValueError("Provide image_ids or all_hidden, but not both")
        return self


async def resolve_bulk_selection(
    request: BulkMetadataRequest | BulkDeleteRequest | BulkActionRequest,
    auth: dict,
) -> list[int]:
    if request.gallery_ids:
        return list(dict.fromkeys(request.gallery_ids))
    redis = get_redis()
    raw = await redis.get(f"explorer:selection:{request.selection_token}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except TypeError, ValueError:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    if payload.get("user_id") != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Selection expired or was not found")
    excluded = set(request.excluded_ids)
    return [int(gallery_id) for gallery_id in payload.get("gallery_ids", []) if int(gallery_id) not in excluded]


async def enqueue_folder_stats(library_id: int, relative_path: str) -> None:
    import core.queue

    try:
        await core.queue.enqueue(
            "explorer_folder_stats_job",
            _job_id=folder_stats_job_id(library_id, relative_path),
            _timeout=3600,
            library_id=library_id,
            relative_path=relative_path,
        )
    except Exception:
        # Navigation remains usable if the worker is unavailable; the UI keeps
        # the size in a pending state and can request a refresh later.
        return
