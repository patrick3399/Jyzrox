"""Request schemas for dataset routes."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DatasetSelection(BaseModel):
    gallery_ids: list[int] = Field(default_factory=list, max_length=500)
    collection_ids: list[int] = Field(default_factory=list, max_length=100)
    image_ids: list[int] = Field(default_factory=list, max_length=2000)
    tag_query: str | None = Field(default=None, max_length=500)
    tag_query_limit: int = Field(default=5000, ge=1, le=5000)

    @field_validator("tag_query")
    @classmethod
    def validate_tag_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DatasetCreate(DatasetSelection):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Dataset name must not be blank")
        return value


class DatasetFilterConfig(BaseModel):
    min_width: int | None = Field(default=None, ge=1, le=100000)
    min_height: int | None = Field(default=None, ge=1, le=100000)
    max_aspect_ratio: float | None = Field(default=None, gt=1.0, le=100.0)
    phash_distance: int | None = Field(default=None, ge=0, le=64)


class ImageCaptionPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=10000)

    @field_validator("caption")
    @classmethod
    def normalize_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CaptionBatchRequest(BaseModel):
    operation: Literal["prepend_trigger", "search_replace"]
    trigger_word: str | None = Field(default=None, max_length=200)
    search: str | None = Field(default=None, max_length=1000)
    replacement: str = Field(default="", max_length=1000)
