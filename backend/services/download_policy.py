"""Credential requirement policy for download sources.

Shared by the download router (HTTP warning/400) and the subscription worker
(skip-and-record), which previously duplicated this logic (architecture
risk #1).
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class CredentialPolicy:
    source_id: str
    source_name: str
    requirement: str  # "required" | "recommended" | "none"
    has_credential: bool
    warning_code: str | None

    @property
    def missing_required(self) -> bool:
        return self.requirement == "required" and not self.has_credential

    @property
    def missing_recommended(self) -> bool:
        return self.requirement == "recommended" and not self.has_credential


async def get_credential_policy(source: str) -> CredentialPolicy:
    """Resolve the credential posture for a download source.

    Imports stay function-local so tests can patch
    ``plugins.builtin.gallery_dl._sites.get_site_config`` and
    ``services.credential.get_credential`` at their source modules.
    """
    from plugins.builtin.gallery_dl._sites import get_site_config
    from services.credential import get_credential

    cfg = get_site_config(source)
    if cfg.credential_requirement not in ("required", "recommended"):
        return CredentialPolicy(
            source_id=cfg.source_id,
            source_name=cfg.name,
            requirement=cfg.credential_requirement,
            has_credential=False,
            warning_code=None,
        )
    cred = await get_credential(cfg.source_id)
    missing_recommended = cfg.credential_requirement == "recommended" and not cred
    return CredentialPolicy(
        source_id=cfg.source_id,
        source_name=cfg.name,
        requirement=cfg.credential_requirement,
        has_credential=bool(cred),
        warning_code=cfg.credential_warning_code if missing_recommended else None,
    )


def normalize_source_options(source: str, options: dict | None) -> dict | None:
    """Apply source-specific download-option policy before persisting a job.

    Raises ValueError when the options are invalid for the source. The fanbox
    dispatch is hard-coded for now; the long-term home is a plugin-registry
    capability (architecture risk #2), but routers should already go through
    this seam instead of importing plugins.builtin internals.
    """
    if source == "fanbox":
        from plugins.builtin.fanbox.policy import normalized_fanbox_options

        return normalized_fanbox_options(options)
    return options


class MediaPolicy(BaseModel):
    """Generic per-job selection: how many of the newest files, and whether videos count."""

    model_config = ConfigDict(extra="forbid")

    max_files: int | None = Field(default=None, ge=1, le=100_000)
    include_videos: bool = True

    @property
    def is_default(self) -> bool:
        return self.max_files is None and self.include_videos


def media_policy_from_options(options: dict | None) -> MediaPolicy | None:
    """Parse ``options.media``; ``None`` means the job keeps today's behaviour."""
    raw = (options or {}).get("media")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("options.media must be an object")
    policy = MediaPolicy.model_validate(raw)
    return None if policy.is_default else policy


async def normalize_download_options(url: str, source: str | None, options: dict | None) -> dict | None:
    """Validate every download-option policy for one URL before a job or subscription is persisted."""
    from plugins.registry import plugin_registry

    normalized = normalize_source_options(source or "", options)
    if source == "pixiv":
        from plugins.builtin.pixiv.source import PixivSourcePlugin

        # A Pixiv author URL belongs to the ``user:{id}`` author collection
        # (pixiv_collection_job). As a plain download it would import a second
        # gallery keyed by its output folder, ``user_{id}``.
        if PixivSourcePlugin.user_match(url):
            normalized = {**(normalized or {}), "pixiv_collection": True}
    if not normalized or "media" not in normalized:
        return normalized
    normalized = dict(normalized)
    policy = media_policy_from_options(normalized)
    if policy is None:
        normalized.pop("media")
        return normalized
    if not await plugin_registry.supports_media_policy(url):
        raise ValueError("media options are not supported for this source")
    normalized["media"] = policy.model_dump(mode="json")
    return normalized
