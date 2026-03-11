from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://redis:6379"

    # Security
    credential_encrypt_key: str
    cors_origin: str = ""  # e.g. "https://vault.example.com" — empty = same-origin only
    cookie_secure: bool = True  # Set to False only for local HTTP dev
    trusted_proxies: str = "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"  # comma-separated CIDRs/IPs

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_login: int = 5  # max attempts per window
    rate_limit_window: int = 300  # window in seconds (5 min)

    # Feature toggles (defaults, overridable at runtime via Redis)
    csrf_enabled: bool = True
    opds_enabled: bool = True
    external_api_enabled: bool = True
    download_eh_enabled: bool = True
    download_pixiv_enabled: bool = True
    download_gallery_dl_enabled: bool = True

    # E-Hentai limits
    eh_max_concurrency: int = 2
    eh_request_timeout: int = 30
    eh_acquire_timeout: int = 60
    eh_use_ex: bool = False  # Use ExHentai instead of E-Hentai (EH_USE_EX env var)
    eh_download_concurrency: int = 3    # parallel images per gallery
    eh_download_max_retries: int = 3    # nl retries per image

    # AI Tagging
    tag_model_enabled: bool = False
    tag_model_name: str = "SmilingWolf/wd-swinv2-tagger-v3"
    tag_general_threshold: float = 0.35
    tag_character_threshold: float = 0.85
    tagger_url: str = "http://tagger:8100"
    tagger_timeout: int = 30

    # Storage paths (inside container)
    data_gallery_path: str = "/data/gallery"
    data_thumbs_path: str = "/data/thumbs"
    data_training_path: str = "/data/training"
    data_avatars_path: str = "/data/avatars"
    data_cas_path: str = "/data/cas"
    data_library_path: str = "/data/library"

    # gallery-dl config (bind-mounted)
    gallery_dl_config: str = "/app/config/gallery-dl.json"

    # Pixiv OAuth (public Android app credentials; override via env if needed)
    pixiv_client_id: str = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    pixiv_client_secret: str = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    # To override: set PIXIV_CLIENT_ID and PIXIV_CLIENT_SECRET in .env

    # Pixiv API limits
    pixiv_max_concurrency: int = 4       # max concurrent API requests
    pixiv_image_concurrency: int = 6     # max concurrent image proxy downloads
    pixiv_request_timeout: int = 30

    # Library management
    library_monitor_enabled: bool = True
    library_scan_interval_hours: int = 24
    extra_library_paths: str = ""  # Comma-separated extra paths
    library_base_path: str = "/mnt"  # Default root for user-mounted external media
    watcher_use_polling: bool = False
    watcher_polling_interval: int = 60  # seconds

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


async def get_all_library_paths() -> list[str]:
    """Return all user-configured library paths.

    Only returns paths the user has explicitly added (via env var or DB).
    Does NOT include ``library_base_path`` (/mnt) automatically — users
    must add paths themselves.  ``data_gallery_path`` (/data/gallery) is
    never included as it is the download engine's internal workspace.
    """
    import os

    paths: list[str] = []

    # From env var
    if settings.extra_library_paths:
        for p in settings.extra_library_paths.split(","):
            p = p.strip()
            if p and p not in paths:
                paths.append(p)

    # From database
    try:
        from core.database import async_session
        from db.models import LibraryPath
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(LibraryPath.path).where(LibraryPath.enabled == True)  # noqa: E712
            )
            for row in result.scalars():
                if row not in paths:
                    paths.append(row)
    except Exception:
        pass  # DB might not be ready during startup

    return paths
