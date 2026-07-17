"""Credential requirement policy for download sources.

Shared by the download router (HTTP warning/400) and the subscription worker
(skip-and-record), which previously duplicated this logic (architecture
risk #1).
"""

from dataclasses import dataclass


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
