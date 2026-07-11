"""Fanbox per-request download policy.

Authentication answers *what the account can access*.  This module answers
*which accessible posts a particular job or subscription wants to download*.
Keeping these separate avoids a global credential setting changing unrelated
creator subscriptions.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class FanboxDownloadPolicy(BaseModel):
    """Selection criteria attached to one download job or subscription."""

    content: Literal["free_only", "accessible", "paid_only", "price_range"] = "accessible"
    fee_min: int | None = Field(default=None, ge=0)
    fee_max: int | None = Field(default=None, ge=0)
    include_images: bool = True
    include_videos: bool = True
    include_files: bool = False

    @model_validator(mode="after")
    def validate_range(self):
        if self.fee_min is not None and self.fee_max is not None and self.fee_min > self.fee_max:
            raise ValueError("fee_min must not exceed fee_max")
        if self.content == "price_range" and self.fee_min is None and self.fee_max is None:
            raise ValueError("price_range requires fee_min or fee_max")
        return self

    def includes_fee(self, fee_required: int) -> bool:
        """Return whether a post price satisfies this policy.

        Actual access is deliberately checked separately after this inexpensive
        summary-level filter.  A paid post is never treated as downloadable
        merely because it matches a price range.
        """
        if self.content == "free_only" and fee_required != 0:
            return False
        if self.content == "paid_only" and fee_required == 0:
            return False
        if self.fee_min is not None and fee_required < self.fee_min:
            return False
        return self.fee_max is None or fee_required <= self.fee_max


def fanbox_policy_from_options(options: dict[str, Any] | None) -> FanboxDownloadPolicy:
    """Parse the nested ``options.fanbox`` value with safe defaults."""
    raw = (options or {}).get("fanbox", {})
    if not isinstance(raw, dict):
        raise ValueError("options.fanbox must be an object")
    return FanboxDownloadPolicy.model_validate(raw)


def normalized_fanbox_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return options with a canonical JSON-safe Fanbox policy embedded."""
    normalized = dict(options or {})
    normalized["fanbox"] = fanbox_policy_from_options(options).model_dump(mode="json")
    return normalized
