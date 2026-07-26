from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

_KEYGEN_HINT = 'python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"'


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

    @field_validator("credential_encrypt_key")
    @classmethod
    def validate_credential_encrypt_key(cls, value: str) -> str:
        if "CHANGE_ME" in value or len(value) < 32:
            raise ValueError(
                "CREDENTIAL_ENCRYPT_KEY must be a real generated secret (at least 32 characters); "
                f"generate one with: {_KEYGEN_HINT}"
            )
        return value

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
    novel_enabled: bool = False  # Novel module ships disabled (needs git secrets + hub); admin opts in
    download_job_timeout: int = 86400

    # E-Hentai limits
    eh_max_concurrency: int = 2
    eh_request_timeout: int = 30
    eh_acquire_timeout: int = 60
    eh_use_ex: bool = False  # Use ExHentai instead of E-Hentai (EH_USE_EX env var)
    eh_download_concurrency: int = 3  # parallel images per gallery
    eh_download_max_retries: int = 3  # nl retries per image

    # AI Tagging
    tag_model_enabled: bool = False
    tag_model_name: str = "SmilingWolf/wd-swinv2-tagger-v3"
    tag_general_threshold: float = 0.35
    tag_character_threshold: float = 0.85
    tagger_url: str = "http://tagger:8100"
    tagger_timeout: int = 30

    # Remote image processing
    swarmui_enabled: bool = False
    swarmui_url: str = ""  # No default host — admin sets it via SWARMUI_URL or the settings UI
    swarmui_timeout: int = 600
    captioner_enabled: bool = False
    captioner_url: str = "http://captioner:8200"
    captioner_timeout: int = 300
    captioner_engine: str = "florence2"

    # Storage paths (inside container)
    data_gallery_path: str = "/data/gallery"
    data_thumbs_path: str = "/data/thumbs"
    data_training_path: str = "/data/training"
    data_avatars_path: str = "/data/avatars"
    data_cas_path: str = "/data/cas"
    data_library_path: str = "/data/library"
    data_backups_path: str = "/data/backups"
    novel_repo_path: str = "/data/novel"
    backup_retention_count: int = 14
    backup_pg_dump_timeout: int = 3600
    # Disk space
    disk_min_free_gb: float = 2.0
    # Container memory alert threshold (percent of the cgroup limit); used by
    # the worker memory_monitor cron and the api memory watch (STAB-011)
    memory_alert_pct: float = 85.0
    # Redis alert threshold as a percentage of its configured maxmemory. Redis
    # stores control-plane state, so pressure must be visible before writes fail.
    redis_memory_alert_pct: float = 85.0
    # api self-sampling cadence (services/memory_watch.py); floor is 30s
    memory_watch_interval_sec: int = 300
    # Log top Python allocation sites each api memory sample (diagnosis only)
    api_tracemalloc: bool = False

    # gallery-dl config (bind-mounted)
    gallery_dl_config: str = "/app/config/gallery-dl.json"

    # Pixiv OAuth (public Android app credentials; override via env if needed)
    pixiv_client_id: str = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    pixiv_client_secret: str = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
    # To override: set PIXIV_CLIENT_ID and PIXIV_CLIENT_SECRET in .env

    # Pixiv API limits
    pixiv_max_concurrency: int = 4  # max concurrent API requests
    pixiv_image_concurrency: int = 6  # max concurrent image proxy downloads
    pixiv_request_timeout: int = 30

    # Library management
    library_monitor_enabled: bool = True
    library_scan_interval_hours: int = 24
    extra_library_paths: str = ""  # Comma-separated extra paths
    library_base_path: str = "/mnt"  # Default root for user-mounted external media
    watcher_use_polling: bool = False
    watcher_polling_interval: int = 60  # seconds

    @property
    def gdl_archive_dsn(self) -> str:
        """Build a psycopg-compatible DSN from the asyncpg database_url.

        Converts: postgresql+asyncpg://user:pass@host:port/db
        To:       postgresql://user:pass@host:port/db
        """
        return self.database_url.replace("+asyncpg", "")

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

    paths: list[str] = []

    # From env var
    if settings.extra_library_paths:
        for p in settings.extra_library_paths.split(","):
            p = p.strip()
            if p and p not in paths:
                paths.append(p)

    # From database
    try:
        from sqlalchemy import select

        from core.database import async_session
        from db.models import LibraryPath

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


async def get_monitored_library_paths() -> list[str]:
    """Return enabled library paths that opted into real-time monitoring.

    Environment-provided paths have no per-path monitor flag and therefore
    remain monitored when the global watcher is enabled. Database paths must
    have both ``enabled`` and ``monitor`` set.
    """
    paths: list[str] = []

    if settings.extra_library_paths:
        for p in settings.extra_library_paths.split(","):
            p = p.strip()
            if p and p not in paths:
                paths.append(p)

    try:
        from sqlalchemy import select

        from core.database import async_session
        from db.models import LibraryPath

        async with async_session() as session:
            result = await session.execute(
                select(LibraryPath.path).where(
                    LibraryPath.enabled == True,  # noqa: E712
                    LibraryPath.monitor == True,  # noqa: E712
                )
            )
            for row in result.scalars():
                if row not in paths:
                    paths.append(row)
    except Exception:
        pass

    return paths
