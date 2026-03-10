"""Structured API error codes with i18n support."""

import logging
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Error translations: code → {locale → message}
# English is always the fallback
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "not_authenticated": {
        "en": "Not authenticated",
        "zh-TW": "未登入",
        "zh-CN": "未登录",
        "ja": "認証されていません",
        "ko": "인증되지 않았습니다",
    },
    "session_invalid": {
        "en": "Invalid session",
        "zh-TW": "無效的工作階段",
        "zh-CN": "无效的会话",
        "ja": "無効なセッション",
        "ko": "유효하지 않은 세션",
    },
    "session_expired": {
        "en": "Session expired",
        "zh-TW": "工作階段已過期",
        "zh-CN": "会话已过期",
        "ja": "セッションの有効期限切れ",
        "ko": "세션이 만료되었습니다",
    },
    "invalid_credentials": {
        "en": "Invalid credentials",
        "zh-TW": "帳號或密碼錯誤",
        "zh-CN": "账号或密码错误",
        "ja": "認証情報が無効です",
        "ko": "잘못된 인증 정보",
    },
    "setup_completed": {
        "en": "Setup already completed",
        "zh-TW": "設定已完成",
        "zh-CN": "设置已完成",
        "ja": "セットアップは完了済みです",
        "ko": "설정이 이미 완료되었습니다",
    },
    "gallery_not_found": {
        "en": "Gallery not found",
        "zh-TW": "找不到圖庫",
        "zh-CN": "找不到图库",
        "ja": "ギャラリーが見つかりません",
        "ko": "갤러리를 찾을 수 없습니다",
    },
    "image_not_found": {
        "en": "Image not found",
        "zh-TW": "找不到圖片",
        "zh-CN": "找不到图片",
        "ja": "画像が見つかりません",
        "ko": "이미지를 찾을 수 없습니다",
    },
    "eh_cookie_invalid": {
        "en": "E-Hentai cookie invalid or expired. Update in Settings → Credentials.",
        "zh-TW": "E-Hentai Cookie 無效或已過期。請至 設定 → 登入資訊 更新。",
        "zh-CN": "E-Hentai Cookie 无效或已过期。请在 设置 → 登录信息 中更新。",
        "ja": "E-Hentai Cookieが無効または期限切れです。設定 → 認証情報で更新してください。",
        "ko": "E-Hentai 쿠키가 유효하지 않거나 만료되었습니다. 설정 → 인증 정보에서 업데이트하세요.",
    },
    "eh_access_denied": {
        "en": "ExHentai access denied (Sad Panda). Configure credentials in Settings → Credentials.",
        "zh-TW": "ExHentai 存取被拒絕（Sad Panda）。請至 設定 → 登入資訊 設定。",
        "zh-CN": "ExHentai 访问被拒绝（Sad Panda）。请在 设置 → 登录信息 中设置。",
        "ja": "ExHentaiアクセスが拒否されました（Sad Panda）。設定 → 認証情報で設定してください。",
        "ko": "ExHentai 접근이 거부되었습니다 (Sad Panda). 설정 → 인증 정보에서 설정하세요.",
    },
    "eh_bandwidth_exceeded": {
        "en": "E-Hentai bandwidth limit exceeded. Configure credentials for higher limits.",
        "zh-TW": "E-Hentai 流量上限已超過。設定登入資訊可提高限額。",
        "zh-CN": "E-Hentai 带宽上限已超过。设置登录信息可提高限额。",
        "ja": "E-Hentai帯域幅制限を超えました。認証情報を設定すると制限が緩和されます。",
        "ko": "E-Hentai 대역폭 제한 초과. 인증 정보를 설정하면 제한이 완화됩니다.",
    },
    "eh_request_failed": {
        "en": "E-Hentai request failed",
        "zh-TW": "E-Hentai 請求失敗",
        "zh-CN": "E-Hentai 请求失败",
        "ja": "E-Hentaiリクエストに失敗しました",
        "ko": "E-Hentai 요청 실패",
    },
    "eh_not_configured": {
        "en": "E-Hentai credentials not configured. Set up in Settings → Credentials.",
        "zh-TW": "未設定 E-Hentai 登入資訊。請至 設定 → 登入資訊 設定。",
        "zh-CN": "未设置 E-Hentai 登录信息。请在 设置 → 登录信息 中设置。",
        "ja": "E-Hentai認証情報が設定されていません。設定 → 認証情報で設定してください。",
        "ko": "E-Hentai 인증 정보가 설정되지 않았습니다. 설정 → 인증 정보에서 설정하세요.",
    },
    "pixiv_token_invalid": {
        "en": "Pixiv token invalid or expired. Re-authenticate in Settings → Credentials.",
        "zh-TW": "Pixiv Token 無效或已過期。請至 設定 → 登入資訊 重新驗證。",
        "zh-CN": "Pixiv Token 无效或已过期。请在 设置 → 登录信息 中重新验证。",
        "ja": "Pixivトークンが無効または期限切れです。設定 → 認証情報で再認証してください。",
        "ko": "Pixiv 토큰이 유효하지 않거나 만료되었습니다. 설정 → 인증 정보에서 재인증하세요.",
    },
    "pixiv_not_configured": {
        "en": "Pixiv credentials not configured. Set up in Settings → Credentials.",
        "zh-TW": "未設定 Pixiv 登入資訊。請至 設定 → 登入資訊 設定。",
        "zh-CN": "未设置 Pixiv 登录信息。请在 设置 → 登录信息 中设置。",
        "ja": "Pixiv認証情報が設定されていません。設定 → 認証情報で設定してください。",
        "ko": "Pixiv 인증 정보가 설정되지 않았습니다. 설정 → 인증 정보에서 설정하세요.",
    },
    "pixiv_request_failed": {
        "en": "Pixiv request failed",
        "zh-TW": "Pixiv 請求失敗",
        "zh-CN": "Pixiv 请求失败",
        "ja": "Pixivリクエストに失敗しました",
        "ko": "Pixiv 요청 실패",
    },
    "eh_credentials_recommended": {
        "en": "Downloading without credentials — bandwidth may be limited.",
        "zh-TW": "未使用登入資訊下載 — 流量可能受限。",
        "zh-CN": "未使用登录信息下载 — 带宽可能受限。",
        "ja": "認証情報なしでダウンロード中 — 帯域幅が制限される場合があります。",
        "ko": "인증 정보 없이 다운로드 중 — 대역폭이 제한될 수 있습니다.",
    },
    "pixiv_credentials_required": {
        "en": "Pixiv credentials required for downloads. Set up in Settings → Credentials.",
        "zh-TW": "下載需要 Pixiv 登入資訊。請至 設定 → 登入資訊 設定。",
        "zh-CN": "下载需要 Pixiv 登录信息。请在 设置 → 登录信息 中设置。",
        "ja": "ダウンロードにはPixiv認証情報が必要です。設定 → 認証情報で設定してください。",
        "ko": "다운로드에 Pixiv 인증 정보가 필요합니다. 설정 → 인증 정보에서 설정하세요.",
    },
    "download_source_disabled": {
        "en": "Download source is disabled",
        "zh-TW": "此下載來源已停用",
        "zh-CN": "此下载来源已停用",
        "ja": "このダウンロードソースは無効です",
        "ko": "이 다운로드 소스가 비활성화되었습니다",
    },
    "credential_not_found": {
        "en": "Credential not found",
        "zh-TW": "找不到登入資訊",
        "zh-CN": "找不到登录信息",
        "ja": "認証情報が見つかりません",
        "ko": "인증 정보를 찾을 수 없습니다",
    },
    "token_not_found": {
        "en": "Token not found",
        "zh-TW": "找不到 Token",
        "zh-CN": "找不到 Token",
        "ja": "トークンが見つかりません",
        "ko": "토큰을 찾을 수 없습니다",
    },
    "invalid_request": {
        "en": "Invalid request",
        "zh-TW": "無效的請求",
        "zh-CN": "无效的请求",
        "ja": "無効なリクエスト",
        "ko": "잘못된 요청",
    },
    "rate_limited": {
        "en": "Too many requests",
        "zh-TW": "請求過於頻繁",
        "zh-CN": "请求过于频繁",
        "ja": "リクエストが多すぎます",
        "ko": "요청이 너무 많습니다",
    },
    "csrf_invalid": {
        "en": "CSRF token missing or invalid",
        "zh-TW": "CSRF Token 遺失或無效",
        "zh-CN": "CSRF Token 丢失或无效",
        "ja": "CSRFトークンが見つからないか無効です",
        "ko": "CSRF 토큰이 없거나 유효하지 않습니다",
    },
    "feature_disabled": {
        "en": "This feature is disabled",
        "zh-TW": "此功能已停用",
        "zh-CN": "此功能已停用",
        "ja": "この機能は無効です",
        "ko": "이 기능은 비활성화되었습니다",
    },
    "file_too_large": {
        "en": "File too large",
        "zh-TW": "檔案過大",
        "zh-CN": "文件过大",
        "ja": "ファイルが大きすぎます",
        "ko": "파일이 너무 큽니다",
    },
    "path_not_allowed": {
        "en": "Path outside allowed directory",
        "zh-TW": "路徑不在允許的目錄內",
        "zh-CN": "路径不在允许的目录内",
        "ja": "許可されたディレクトリ外のパス",
        "ko": "허용된 디렉토리 외부 경로",
    },
    "login_failed": {
        "en": "Login failed: incorrect username or password",
        "zh-TW": "登入失敗：帳號或密碼錯誤",
        "zh-CN": "登录失败：账号或密码错误",
        "ja": "ログイン失敗：ユーザー名またはパスワードが正しくありません",
        "ko": "로그인 실패: 사용자 이름 또는 비밀번호가 올바르지 않습니다",
    },
    "job_not_found": {
        "en": "Job not found",
        "zh-TW": "找不到任務",
        "zh-CN": "找不到任务",
        "ja": "ジョブが見つかりません",
        "ko": "작업을 찾을 수 없습니다",
    },
    "tag_not_found": {
        "en": "Tag not found",
        "zh-TW": "找不到標籤",
        "zh-CN": "找不到标签",
        "ja": "タグが見つかりません",
        "ko": "태그를 찾을 수 없습니다",
    },
    "not_found": {
        "en": "Not found",
        "zh-TW": "找不到",
        "zh-CN": "找不到",
        "ja": "見つかりません",
        "ko": "찾을 수 없습니다",
    },
    "unknown_feature": {
        "en": "Unknown feature",
        "zh-TW": "未知的功能",
        "zh-CN": "未知的功能",
        "ja": "不明な機能",
        "ko": "알 수 없는 기능",
    },
    "server_error": {
        "en": "Internal server error",
        "zh-TW": "伺服器內部錯誤",
        "zh-CN": "服务器内部错误",
        "ja": "サーバー内部エラー",
        "ko": "서버 내부 오류",
    },
}

SUPPORTED_LOCALES = {"en", "zh-TW", "zh-CN", "ja", "ko"}


def parse_accept_language(header: str | None) -> str:
    """Parse Accept-Language header, return best matching locale."""
    if not header:
        return "en"

    # Parse "en-US,en;q=0.9,zh-TW;q=0.8" format
    best_locale = "en"
    best_q = 0.0

    for part in header.split(","):
        part = part.strip()
        if not part:
            continue

        # Split "lang;q=0.8" or just "lang"
        segments = part.split(";")
        lang = segments[0].strip()
        q = 1.0
        for seg in segments[1:]:
            seg = seg.strip()
            if seg.startswith("q="):
                try:
                    q = float(seg[2:])
                except ValueError:
                    q = 0.0

        # Try exact match first
        if lang in SUPPORTED_LOCALES and q > best_q:
            best_q = q
            best_locale = lang
            continue

        # Try prefix match (e.g., "zh" → "zh-TW", "zh-Hans" → "zh-CN")
        lang_lower = lang.lower()
        if lang_lower.startswith("zh-hans") or lang_lower == "zh-cn":
            if q > best_q and "zh-CN" in SUPPORTED_LOCALES:
                best_q = q
                best_locale = "zh-CN"
        elif lang_lower.startswith("zh"):
            if q > best_q and "zh-TW" in SUPPORTED_LOCALES:
                best_q = q
                best_locale = "zh-TW"
        elif lang_lower.startswith("ja") and q > best_q:
            best_q = q
            best_locale = "ja"
        elif lang_lower.startswith("ko") and q > best_q:
            best_q = q
            best_locale = "ko"

    return best_locale


def get_error_message(code: str, locale: str = "en", **kwargs) -> str:
    """Get translated error message for a code."""
    translations = _TRANSLATIONS.get(code, {})
    msg = translations.get(locale) or translations.get("en", code)
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return msg


def api_error(
    status_code: int,
    code: str,
    locale: str = "en",
    **kwargs,
) -> HTTPException:
    """Create an HTTPException with structured i18n detail."""
    message = get_error_message(code, locale, **kwargs)
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )
