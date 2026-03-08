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

    # E-Hentai limits
    eh_max_concurrency: int = 2
    eh_request_timeout: int = 30
    eh_acquire_timeout: int = 60
    eh_use_ex: bool = False  # Use ExHentai instead of E-Hentai (EH_USE_EX env var)
    eh_download_concurrency: int = 3    # parallel images per gallery
    eh_download_max_retries: int = 3    # nl retries per image

    # AI Tagging
    tag_model_enabled: bool = False

    # Storage paths (inside container)
    data_gallery_path: str = "/data/gallery"
    data_thumbs_path: str = "/data/thumbs"
    data_training_path: str = "/data/training"
    data_avatars_path: str = "/data/avatars"

    # gallery-dl config (bind-mounted)
    gallery_dl_config: str = "/app/config/gallery-dl.json"

    # Pixiv OAuth
    pixiv_client_id: str = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    pixiv_client_secret: str = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"

    model_config = {"env_file": ".env", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
