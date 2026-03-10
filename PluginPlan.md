# Plugin Architecture Refactor Plan

## Context

現有 plugin 系統有幾個架構問題：
- BrowsePlugin ABC 沒被實際使用（router 直接呼叫 service）
- `parse_metadata()` 是死代碼（worker 自己做 source-specific 解析）
- SITE_REGISTRY、plugin registry、worker `_detect_source` 三處重複 URL→source 映射
- Credential 流程在 `routers/settings.py` 裡 hardcoded，和 plugin 系統脫節
- Subscription 檢查是純 Pixiv 代碼，無抽象

目標：趁沒有使用者，大膽重構成乾淨的 plugin 架構。不需向後相容。

---

## 設計原則

1. **Plugin = Source Bundle** — 一個 source 一個 plugin package，實作多個 interface
2. **Interface 用 Protocol** — 各 capability 是獨立 Protocol，plugin 按需實作
3. **Browse Router 由 plugin 提供** — 每個 browse plugin 提供自己的 FastAPI router，動態掛載
4. **Metadata 回歸 plugin** — import pipeline 真正呼叫 plugin 的 metadata 解析
5. **SITE_REGISTRY 併入 plugin** — gallery-dl 註冊它支援的所有 sites
6. **Credential 由 plugin 宣告** — 含 flow type（simple / oauth / login）

---

## Plugin Interface 設計

### 基礎

```python
# plugins/base.py

class PluginMeta(BaseModel):
    name: str                    # "E-Hentai"
    source_id: str               # "ehentai"
    version: str                 # "1.0.0"
    description: str             # 簡短描述
    url_patterns: list[str]      # ["e-hentai.org", "exhentai.org"]
    supported_sites: list[SiteInfo]  # 取代 SITE_REGISTRY
    concurrency: int = 1

class SiteInfo(BaseModel):
    domain: str
    name: str
    category: str       # "gallery", "art", "social", "booru", ...
    has_tags: bool = False
```

### 6 個 Capability Protocol

```python
# 1. Download — 下載引擎
class Downloadable(Protocol):
    async def can_handle(self, url: str) -> bool
    async def download(self, url: str, dest_dir: Path, credentials: dict | None, ...) -> DownloadResult

# 2. Browsable — 瀏覽器（提供 FastAPI router）
class Browsable(Protocol):
    def get_browse_router(self) -> APIRouter

# 3. Parseable — 下載後的 metadata 解析（取代死掉的 parse_metadata）
class Parseable(Protocol):
    def parse_import(self, dest_dir: Path, raw_meta: dict | None) -> GalleryImportData

# 4. Subscribable — 訂閱/追蹤 artist 新作
class Subscribable(Protocol):
    async def check_new_works(self, artist_id: str, last_known: str | None, credentials: dict | None) -> list[NewWork]

# 5. CredentialProvider — 宣告 credential 需求與驗證
class CredentialProvider(Protocol):
    def credential_flows(self) -> list[CredentialFlow]
    async def verify_credential(self, credentials: dict) -> CredentialStatus

# 6. Taggable — AI tagging
class Taggable(Protocol):
    async def tag_images(self, image_paths: list[Path]) -> list[TagResult]
```

### CredentialFlow 類型

```python
class CredentialFlow(BaseModel):
    flow_type: Literal["fields", "oauth", "login"]
    fields: list[FieldDef]          # "fields" type: 簡單表單
    oauth_config: OAuthConfig | None  # "oauth" type: PKCE flow
    login_endpoint: str | None       # "login" type: 帳密登入 endpoint
    verify_endpoint: str | None      # 驗證已存 credential

class OAuthConfig(BaseModel):
    auth_url_endpoint: str    # 取得 OAuth URL 的 API path
    callback_endpoint: str    # 回傳 code 的 API path
    display_name: str         # "Pixiv OAuth Login"
```

---

## 各 Plugin 實作

### E-Hentai Plugin (`plugins/builtin/ehentai/`)

```
plugins/builtin/ehentai/
├── __init__.py          # EhPlugin class（實作 5 個 Protocol）
├── download.py          # Downloadable 實作（現有 source.py）
├── browse.py            # Browsable 實作（提供 router，吸收現有 routers/eh.py）
├── metadata.py          # Parseable 實作（從 worker.py 搬出 EH-specific 解析）
├── credentials.py       # CredentialProvider（EH cookie 流程）
└── subscribe.py         # Subscribable（追蹤 uploader 新作，未來）
```

**Capabilities**: Downloadable, Browsable, Parseable, CredentialProvider, (Subscribable 未來)

### Pixiv Plugin (`plugins/builtin/pixiv/`)

```
plugins/builtin/pixiv/
├── __init__.py
├── download.py          # Downloadable
├── browse.py            # Browsable（吸收現有 routers/pixiv.py）
├── metadata.py          # Parseable（從 worker.py 搬出 Pixiv-specific 解析）
├── credentials.py       # CredentialProvider（OAuth PKCE + cookie + token 三種流程）
└── subscribe.py         # Subscribable（現有 check_followed_artists 搬入）
```

**Capabilities**: Downloadable, Browsable, Parseable, CredentialProvider, Subscribable

### gallery-dl Plugin (`plugins/builtin/gallery_dl/`)

```
plugins/builtin/gallery_dl/
├── __init__.py
├── download.py          # Downloadable（fallback）
├── metadata.py          # Parseable（通用 gallery-dl JSON 解析 + source-specific 分支）
└── credentials.py       # CredentialProvider（generic cookie 表單）
```

**Capabilities**: Downloadable, Parseable, CredentialProvider
**特殊**:
- `supported_sites` 註冊 30+ sites（取代 SITE_REGISTRY）
- `download` 時接收所有 credentials（保持現有行為）
- `parse_import` 處理各 source 的 metadata 格式差異（Twitter handle、booru tag 映射等）

### WD14 Tagger (`plugins/builtin/wd14/`)

```
plugins/builtin/wd14/
├── __init__.py
└── tagger.py            # Taggable
```

**Capabilities**: Taggable

---

## Registry 重構

```python
# plugins/registry.py

class PluginRegistry:
    def register(self, plugin) -> None

    # Download
    async def get_downloader(self, url: str) -> Downloadable | None
    def get_fallback_downloader(self) -> Downloadable | None

    # Browse — 收集所有 browse router
    def get_browse_routers(self) -> list[tuple[str, APIRouter]]  # (source_id, router)

    # Metadata
    def get_parser(self, source_id: str) -> Parseable | None

    # Subscription
    def get_subscribable(self, source_id: str) -> Subscribable | None
    def list_subscribable(self) -> list[str]  # source_ids

    # Credentials
    def get_credential_provider(self, source_id: str) -> CredentialProvider | None
    def list_credential_providers(self) -> list[tuple[str, list[CredentialFlow]]]

    # Tagger
    def get_tagger(self, source_id: str) -> Taggable | None

    # Site info（取代 SITE_REGISTRY）
    def get_all_sites(self) -> list[SiteInfo]
    def detect_source(self, url: str) -> str | None  # 取代 core/utils.py 的函數
    def get_supported_sites_grouped(self) -> dict[str, list[SiteInfo]]  # 取代 get_supported_sites()
```

---

## Worker.py 拆分（2486 行 → 模組化）

worker.py 是目前最大的上帝物件（2486 行、33 個函數）。拆分分兩層：
1. **Source-specific 邏輯 → Plugin**（和 plugin 重構一起做）
2. **通用邏輯 → 獨立模組**（降低單檔複雜度）

### Worker 模組化結構

```
backend/
├── worker.py              # 精簡為 ARQ entry point + WorkerSettings（~100 行）
├── worker/
│   ├── __init__.py
│   ├── download.py        # download_job, _set_job_status, _set_job_progress（~250 行）
│   ├── importer.py        # import_job, local_import_job, batch_import_job（~500 行）
│   ├── scan.py            # rescan_library_job, rescan_gallery_job, rescan_by_path_job,
│   │                      # rescan_library_path_job, auto_discover_job（~700 行）
│   ├── thumbnail.py       # thumbnail_job, _ffprobe_metadata, _extract_video_frame（~150 行）
│   ├── reconciliation.py  # reconciliation_job（~300 行）
│   ├── tagging.py         # tag_job（~100 行）
│   ├── subscription.py    # scheduled_scan_job, cron helpers（~100 行，通用調度）
│   └── utils.py           # _validate_image_magic, _sha256（~50 行）
```

### Source-specific 邏輯搬入 Plugin

以下是 worker.py 中所有 source-specific 分支邏輯的完整清單：

#### A. `download_job()` 中的 source-specific 邏輯

| 邏輯 | 行數 | 搬移目標 | 新 Plugin 方法 |
|------|------|---------|---------------|
| Credential gating（EH/Pixiv 必須有 credential）| 200-210 | Plugin | `requires_credentials() -> bool` |
| Output directory routing（EH regex gid、Pixiv regex illust_id）| 213-233 | Plugin | `resolve_output_dir(url, base_path) -> Path` |
| Semaphore key 選擇（hardcoded ehentai/pixiv/other）| 236 + startup:108 | Plugin | `PluginMeta.semaphore_key: str` |

#### B. `import_job()` / `_build_gallery()` 中的 source-specific 邏輯

| 邏輯 | 行數 | 搬移目標 | 新 Plugin 方法 |
|------|------|---------|---------------|
| Source detection from path（ehentai/pixiv in path）| 434-444 | Plugin | `Parseable.detect_source(path) -> str` |
| Artist ID extraction（EH tags、Pixiv uploader、Twitter author、Booru artist）| 625-649 | Plugin | `Parseable.extract_artist(meta, tags) -> str` |
| Tag namespace 映射（`_BOORU_SOURCES` hardcoded list + namespace rename）| 587-603 | Plugin | `Parseable.normalize_tags(tags) -> list` |
| `backfill_artist_ids()`（artist 邏輯的重複代碼）| 2396-2430 | 刪除 | 改呼叫 plugin 的 `extract_artist()` |

#### C. Subscription 邏輯

| 邏輯 | 行數 | 搬移目標 |
|------|------|---------|
| `check_followed_artists()`（純 Pixiv、130 行）| 2132-2261 | `plugins/builtin/pixiv/subscribe.py` |
| `check_single_subscription()` Pixiv 分支 | 2274-2344 | `plugins/builtin/pixiv/subscribe.py` |
| `check_single_subscription()` generic 分支 | 2358-2376 | `worker/subscription.py`（通用調度） |

### Downloadable Protocol 補充方法

```python
class Downloadable(Protocol):
    async def can_handle(self, url: str) -> bool
    async def download(self, url: str, dest_dir: Path, credentials: dict | None, ...) -> DownloadResult
    def resolve_output_dir(self, url: str, base_path: Path) -> Path    # 新增
    def requires_credentials(self) -> bool                              # 新增
```

### PluginMeta 補充欄位

```python
class PluginMeta(BaseModel):
    # ...existing fields...
    semaphore_key: str | None = None    # 新增：用於 download 限速，None 則用 "other"
```

---

## 要搬移的代碼

### 1. `routers/eh.py` → `plugins/builtin/ehentai/browse.py`
- 12 個 endpoint 搬入 plugin 提供的 router
- 保留 `services/eh_client.py` 作為底層實作
- Plugin 的 `get_browse_router()` 回傳這個 router

### 2. `routers/pixiv.py` → `plugins/builtin/pixiv/browse.py`
- 7 個 endpoint 搬入 plugin 提供的 router
- 保留 `services/pixiv_client.py`

### 3. `routers/settings.py` credential 部分 → 各 plugin 的 `credentials.py`
- EH credential endpoints（login、cookie save、verify、account info）→ EH plugin
- Pixiv credential endpoints（OAuth、cookie exchange、token save）→ Pixiv plugin
- Generic cookie endpoint → gallery-dl plugin 或獨立 credential router
- `services/credential.py`（加解密）保留為共用 service

### 4. `worker.py` source-specific import 邏輯 → 各 plugin 的 `metadata.py`
- `_build_gallery` 裡的 source-specific artist 抽取（lines 624-653）
- Tag namespace 映射（lines 590-602）+ `_BOORU_SOURCES` 常數
- Source ID 提取（line 447）
- `backfill_artist_ids()` 重複邏輯（lines 2396-2430）→ 刪除，改用 plugin
- `import_job` 改為呼叫 `registry.get_parser(source_id).parse_import()`

### 5. `core/utils.py` SITE_REGISTRY → plugin registration
- 刪除 `SITE_REGISTRY`、`detect_source()`、`detect_source_info()`、`get_supported_sites()`
- 改用 `plugin_registry.detect_source()`、`plugin_registry.get_supported_sites_grouped()`
- 所有 caller（`routers/download.py`、`worker.py`、`routers/subscriptions.py`）改用 registry

### 6. `worker.py` subscription 邏輯 → plugin + worker module
- `check_followed_artists`（130 行）→ `plugins/builtin/pixiv/subscribe.py`
- `check_single_subscription` Pixiv 分支 → `plugins/builtin/pixiv/subscribe.py`
- 通用調度邏輯 → `worker/subscription.py`
- Worker cron 改為遍歷 `registry.list_subscribable()` 呼叫各 plugin

### 7. `worker.py` 通用邏輯 → worker/ 模組（與 plugin 無關）
- Library scanning（~700 行）→ `worker/scan.py`
- Thumbnail generation（~150 行）→ `worker/thumbnail.py`
- Reconciliation（~300 行）→ `worker/reconciliation.py`
- AI tagging（~100 行）→ `worker/tagging.py`
- Utilities → `worker/utils.py`

---

## Router 掛載方式

```python
# main.py
async def startup():
    await init_plugins()

    # 動態掛載 browse routers
    for source_id, router in plugin_registry.get_browse_routers():
        app.include_router(router, prefix=f"/api/{source_id}")

    # Credential router（通用）
    app.include_router(credential_router, prefix="/api/credentials")
```

前端 API 路徑不變：`/api/eh/search`、`/api/pixiv/search` 等。

---

## 前端影響

### `/credentials` 頁面
- 改為從 `/api/credentials/flows` 動態取得各 plugin 的 credential flow
- flow_type="fields" → 動態渲染表單
- flow_type="oauth" → 渲染 OAuth 按鈕 + callback 處理
- flow_type="login" → 渲染帳密表單
- EH/Pixiv 的複雜 UI 仍可保留為 source-specific component，但由 plugin 驅動

### `/queue` 頁面
- `supportedSites` API 改從 plugin registry 取（API 不變，只是後端來源變了）

### `/browse`、`/pixiv` 等頁面
- API 路徑不變，前端不需改動

---

## 要刪除的檔案/代碼

- `routers/eh.py` → 搬入 plugin（刪除）
- `routers/pixiv.py` → 搬入 plugin（刪除）
- `routers/settings.py` credential 區段 → 搬入 plugin（精簡）
- `core/utils.py` SITE_REGISTRY 相關 → 刪除
- `worker.py` source-specific import 邏輯 → 搬入 plugin（精簡）
- `worker.py` `check_followed_artists` → 搬入 plugin
- `plugins/base.py` 舊 ABC → 重寫為 Protocol

---

## 實施順序

### Phase 1: Worker 模組拆分（降低複雜度，不改行為）
1. 建立 `worker/` 目錄結構
2. 搬移通用邏輯：scan、thumbnail、reconciliation、tagging、utils
3. `worker.py` 精簡為 ARQ entry point，import 各模組
4. 確認所有 job 仍正常運作（pytest + 手動測試）

### Phase 2: Plugin 基礎架構
5. 定義新的 Protocol interfaces（`plugins/base.py`）— 含補充的 `resolve_output_dir`、`requires_credentials`、`semaphore_key`
6. 重構 PluginRegistry（`plugins/registry.py`）— 含 site info、source detection
7. 新增 `GalleryImportData`、`NewWork`、`CredentialFlow`、`SiteInfo` 等 model

### Phase 3: 各 Plugin 重組
8. EH plugin — 搬入 browse router + metadata（artist 抽取）+ credentials + download（output dir routing）
9. Pixiv plugin — 搬入 browse router + metadata + credentials + subscribe + download
10. gallery-dl plugin — 搬入 metadata（booru tag 映射、通用 artist 抽取）+ credentials + SITE_REGISTRY

### Phase 4: Worker 整合
11. `worker/download.py` — 改用 plugin 的 `resolve_output_dir`、`requires_credentials`、`semaphore_key`
12. `worker/importer.py` — import pipeline 改用 `Parseable`，刪除 source-specific 分支
13. `worker/subscription.py` — 改用 `Subscribable`，刪除 Pixiv hardcode
14. 刪除 `backfill_artist_ids()` 重複邏輯
15. 刪除舊的 `routers/eh.py`、`routers/pixiv.py`
16. 刪除 `core/utils.py` SITE_REGISTRY
17. `main.py` 改為動態掛載 browse routers

### Phase 5: 前端
18. `/credentials` 頁面改為 plugin-driven
19. `/queue` supportedSites API 改為 plugin-based

### Phase 6: 驗證
- `pytest` — 所有現有測試通過
- `next build` — 前端編譯通過
- 手動測試：EH browse、Pixiv browse、下載、credential 儲存、subscription 檢查
- `docker compose build` — 容器建置通過

---

## 關鍵檔案清單

| 檔案 | 動作 |
|------|------|
| **Worker 拆分** | |
| `backend/worker.py` | 精簡為 ARQ entry point（~100 行） |
| `backend/worker/download.py` | 新建（download_job 等，~250 行） |
| `backend/worker/importer.py` | 新建（import_job 等，~500 行） |
| `backend/worker/scan.py` | 新建（rescan 相關，~700 行） |
| `backend/worker/thumbnail.py` | 新建（thumbnail_job，~150 行） |
| `backend/worker/reconciliation.py` | 新建（reconciliation_job，~300 行） |
| `backend/worker/tagging.py` | 新建（tag_job，~100 行） |
| `backend/worker/subscription.py` | 新建（通用 subscription 調度，~100 行） |
| `backend/worker/utils.py` | 新建（_validate_image_magic 等，~50 行） |
| **Plugin 架構** | |
| `backend/plugins/base.py` | 重寫（Protocol interfaces） |
| `backend/plugins/models.py` | 擴充（新 model） |
| `backend/plugins/registry.py` | 重構 |
| `backend/plugins/__init__.py` | 更新 init_plugins |
| `backend/plugins/builtin/ehentai/` | 重組（加 browse/metadata/credentials） |
| `backend/plugins/builtin/pixiv/` | 重組（加 browse/metadata/credentials/subscribe） |
| `backend/plugins/builtin/gallery_dl/` | 擴充（metadata/credentials/sites） |
| **Router 搬移/刪除** | |
| `backend/routers/eh.py` | 刪除（搬入 plugin） |
| `backend/routers/pixiv.py` | 刪除（搬入 plugin） |
| `backend/routers/settings.py` | 精簡（移除 credential 區段） |
| `backend/routers/download.py` | 改用 registry |
| `backend/core/utils.py` | 刪除 SITE_REGISTRY 相關 |
| `backend/main.py` | 動態 router 掛載 |
| **前端** | |
| `pwa/src/app/credentials/page.tsx` | 重構為 plugin-driven |
| `pwa/src/lib/api.ts` | 新增 credential flow API |
