"""Request schemas for the credential settings routers."""

from pydantic import BaseModel, Field

from services.credential import ACCOUNT_PATTERN


class AccountScoped(BaseModel):
    """Save requests may name the account to write; omitted means the active account."""

    account: str | None = Field(default=None, pattern=ACCOUNT_PATTERN)


class EhCookieRequest(AccountScoped):
    ipb_member_id: str
    ipb_pass_hash: str
    sk: str | None = None
    igneous: str | None = None


class EhLoginRequest(AccountScoped):
    username: str
    password: str


class PixivTokenRequest(AccountScoped):
    refresh_token: str


class PixivCookieRequest(AccountScoped):
    phpsessid: str


class PixivOAuthCallbackRequest(AccountScoped):
    code: str
    code_verifier: str


class GenericCookieRequest(AccountScoped):
    source: str
    cookies: dict[str, str]


class SiteCredentialRequest(AccountScoped):
    source: str
    cookies: str | None = None
    username: str | None = None
    password: str | None = None


class SaucenaoApiKeyRequest(AccountScoped):
    api_key: str


# ── Credentials ──────────────────────────────────────────────────────
