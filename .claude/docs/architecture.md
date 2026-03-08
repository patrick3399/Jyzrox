# Jyzrox — Architecture Reference

詳細架構參考文件。Agent 工作時可按需讀取。

---

## 目錄結構

```
Jyzrox/
├── backend/
│   ├── main.py              # FastAPI app + router 註冊
│   ├── worker.py            # ARQ workers (download/import/thumbnail/tag)
│   ├── requirements.txt
│   ├── core/
│   │   ├── config.py        # Pydantic Settings（從 .env 讀取）
│   │   ├── auth.py          # require_auth FastAPI dependency
│   │   ├── database.py      # AsyncSessionLocal, async_session, get_db
│   │   └── redis_client.py
│   ├── db/
│   │   └── models.py        # SQLAlchemy ORM models
│   ├── routers/             # 各功能路由
│   └── services/
│       ├── cache.py         # Redis cache helpers
│       ├── credential.py    # AES-256-GCM 加密存取
│       └── eh_client.py     # E-Hentai HTTP client
├── pwa/
│   └── src/
│       ├── app/             # Next.js App Router 頁面
│       ├── components/      # 共用元件（含 Reader/）
│       ├── hooks/           # SWR hooks
│       ├── lib/
│       │   ├── api.ts       # 所有 API 呼叫（唯一出口）
│       │   └── types.ts     # TypeScript 型別定義
│       └── middleware.ts    # 未登入導向 /login
├── db/
│   └── init.sql             # PostgreSQL schema + GIN index
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
├── docker-compose.override.yml  # dev: user=1000:1000
└── .env                         # 機密設定（不進 git）
```

---

## API Router 對照表

```
/api/auth        → routers/auth.py
/api/system      → routers/system.py
/api/eh          → routers/eh.py
/api/library     → routers/library.py
/api/download    → routers/download.py
/api/settings    → routers/settings.py
/api/ws          → routers/ws.py        (WebSocket: /api/ws/ws)
/api/search      → routers/search.py
/api/tags        → routers/tag.py
/api/import      → routers/import_router.py
/api/export      → routers/export.py   (Kohya zip)
/api/external/v1 → routers/external.py (X-API-Token 認證)
```

---

## 核心設定（core/config.py）

重要欄位：
- `data_gallery_path` = `/data/gallery`（圖片儲存根目錄）
- `data_thumbs_path` = `/data/thumbs`
- `data_training_path` = `/data/training`
- `redis_url`, `database_url`, `credential_encrypt_key`
- `eh_max_concurrency` = 2（EH 圖片代理並發限制）
- `tag_model_enabled` = false（AI 標籤功能，預設關閉）

> ❌ 不存在 `settings.storage_dir`，用 `settings.data_gallery_path`

---

## 資料庫 Schema 重點

- `galleries`：`(source, source_id)` UNIQUE，`tags_array TEXT[]` GIN index
- `images`：`media_type TEXT DEFAULT 'image'`，`duplicate_of BIGINT`（SHA256 去重）
- `tags`：`(namespace, name)` UNIQUE，`count` 計數
- `tag_aliases`、`tag_implications`：Tag 別名與蘊含關係
- `credentials`：AES-256-GCM 加密存儲 EH cookie / Pixiv token
- `api_tokens`：外部 API token（X-API-Token header）
- `read_progress`：閱讀進度（per gallery）

ORM model 在 `backend/db/models.py`，需與 `db/init.sql` 保持一致。

---

## Worker Pipeline（ARQ）

```
download_job → import_job → thumbnail_job
```

- **download_job**：呼叫 gallery-dl subprocess，完成後 enqueue import
- **import_job**：掃描目錄、upsert gallery/images/tags 到 DB，enqueue thumbnail
- **thumbnail_job**：Pillow 生成 160/360/720px WebP，更新 `thumb_path` 和尺寸
- **tag_job**：WD14 AI 標籤（stub，`TAG_MODEL_ENABLED=false` 時跳過）

本地匯入路徑：`data_gallery_path / "local" / {gallery_id}/`

---

## 前端規範

### API 呼叫
- **所有 API 呼叫統一走 `pwa/src/lib/api.ts`**，不直接 `fetch`
- `apiFetch` 自動帶 `credentials: 'include'`（cookie）
- `auth.login(username, password)` 送 `{username, password}`

### SWR Hooks
- `hooks/useGalleries.ts`：library、EH search
- `hooks/useDownloadQueue.ts`：jobs（3s refresh interval）
- `hooks/useAuth.ts`：`login(username, password)`、`logout()`

### Reader 元件
- `components/Reader/index.tsx`：主元件（single/webtoon/double 三種模式）
- `components/Reader/hooks.ts`：所有 hooks（prefetch、touch、keyboard、progress）
- Proxy 模式下序列預載（1次1張），本地模式並行預載 3 張
- 閱讀進度 2 秒 debounce 後存入 DB

### 頁面列表
```
/           Dashboard（最近入庫 + 下載狀態）
/browse     E-Hentai 瀏覽 + 快速下載
/library    本地圖庫（tag/rating/source 篩選）
/library/[id]  圖庫詳情（tag 分組、縮圖預覽）
/reader/[galleryId]  閱讀器
/queue      下載佇列管理
/tags       Tag 列表 + alias/implication 編輯
/settings   憑證設定（EH cookie, Pixiv token）+ 系統資訊
/login      登入（username + password）
/setup      首次設定（建立 admin 帳號）
```

---

## 網路架構

- Nginx 容器僅監聽 HTTP（port 80），**設計上透過外部反向代理（如 Caddy / Traefik / cloud LB）終止 TLS**
- 外部代理負責 HTTPS 憑證、HTTP→HTTPS 重導向
- `cookie_secure` 預設 `True`，在外部代理提供 HTTPS 時正常運作；純 HTTP 開發時需設 `COOKIE_SECURE=false`

---

## Tag 系統

Tag 格式：`{namespace}:{name}`

命名空間（固定）：`artist` / `character` / `copyright` / `general` / `meta` / `language`

### Tag Alias（別名合併）

`tag_aliases` 表：將多個名稱指向同一個 canonical tag。

| 欄位 | 說明 |
|------|------|
| `alias_namespace` | 別名的 namespace |
| `alias_name` | 別名（如 `blue hair`、`藍髮`） |
| `canonical_id` | 指向 `tags.id`（canonical tag） |

行為：導入/搜尋時 alias 自動解析為 canonical；`/tags` 頁面可管理。

### Tag Implication（含義推導）

`tag_implications` 表：定義 A → B 的推導關係。

| 欄位 | 說明 |
|------|------|
| `antecedent_id` | 前提 tag（如 `character:rem`） |
| `consequent_id` | 推導 tag（如 `copyright:re_zero`） |

行為：遞迴展開（A→B→C），展開在寫入 DB 時發生（`tags_array` 包含完整展開列表）。

### Tag 同步流程

```
解析 metadata.json / tags.txt
→ 每個 tag 查 alias → 替換為 canonical
→ 每個 canonical tag 展開 implication
→ 去重後寫入 gallery_tags + 更新 tags_array
→ 更新 tags.count 統計
```

---

## 搜尋系統

統一端點：`GET /api/search?q=...&sort=...&page=...`

### 搜尋語法

| 語法 | 說明 |
|------|------|
| `character:rem` | Tag 精確搜尋（GIN 索引） |
| `-general:sketch` | 排除 tag |
| `character:rem general:blue_hair` | AND（空格分隔） |
| `title:"re zero"` | 標題模糊搜尋（pg_trgm） |
| `source:ehentai` | 來源篩選（ehentai / pixiv / import） |
| `rating:>=4` | 評分篩選 |
| `pages:>=20` | 頁數篩選 |
| `favorited:true` | 已收藏 |
| `language:japanese` | 語言篩選 |

### 排序選項

`sort:added_at`（預設）、`sort:rating`、`sort:posted_at`、`sort:pages`、`sort:title`

### 實作細節

- Tag 搜尋：`tags_array @> ARRAY[...]`（GIN 索引），排除用 `&&`
- 標題模糊搜尋：`pg_trgm` 擴充 + GIN index（`gin_trgm_ops`）
- Tag Autocomplete：`tags` 表前綴匹配 + alias 查找，依 `count DESC` 排序

---

## SHA256 去重機制

去重時機：`import_job` 導入每個檔案時。

| 情境 | 行為 |
|------|------|
| 同 gallery 內重複 | 跳過，記 log |
| 跨 gallery 重複 | 仍匯入，`images.duplicate_of` 設為原始 image.id |
| 不存在 | 正常匯入 |

- 僅用 SHA256（完全相同），**不做感知雜湊**（perceptual hash）
- Copy Mode 跨 gallery 重複時建立硬連結節省空間

---

## 影片 / GIF 支援

`images.media_type` 欄位：`'image'` / `'video'` / `'gif'`

| 類型 | Reader 行為 | 縮圖 |
|------|------------|------|
| `image` | `<img>` | Pillow WebP |
| `video` | `<video controls autoplay loop>` | ffmpeg 擷取首幀 |
| `gif` | `<img>` | 取第一幀靜態縮圖 |

支援格式：`.mp4`、`.webm`、`.gif`（不做伺服器端轉碼）
Nginx 對影片檔提供 HTTP Range Request 支援（可拖曳時間軸）。

---

## 匯入模式

兩種模式均執行 SHA256 去重 + Tag 同步流程。

| 模式 | 端點 | 行為 |
|------|------|------|
| Link Mode | `POST /api/import/link { path, recursive }` | 唯讀；`file_path` 指向外部絕對路徑；不複製檔案；縮圖仍寫入 `/data/thumbs/` |
| Copy Mode | `POST /api/import/copy { path }` | 檔案從 `/data/imports/` 複製至 `/data/gallery/imports/{id}/`；原始檔移至 `/data/imports/_done/` |

---

## Redis Key 模式

```
session:{user_id}:{token}      → session 資料（TTL 30 天）
job:{job_id}                   → 下載任務狀態
eh:gallery:{gid}               → EH gallery 快取（TTL 1h）
eh:imagelist:{gid}             → 圖片列表快取（TTL 1h）
thumb:proxied:{gid}:{page}     → 代理圖片快取（TTL 24h）
eh:semaphore                   → 全域併發計數
system:alerts                  → 系統警告列表
```

---

## 檔案系統佈局

```
/data/
├── gallery/
│   ├── ehentai/{gid}/          # 下載的 EH 圖庫
│   ├── pixiv/{artist_id}/{work_id}/
│   └── imports/{id}/           # Copy Mode 匯入
├── imports/                    # Copy Mode 來源（使用者放入）
│   └── _done/                  # 已處理的原始檔
├── thumbs/
│   └── {hash[:2]}/{hash}/      # 160/360/720px WebP
└── training/
    └── {dataset_name}/         # Kohya 格式匯出
```

Link Mode 的檔案不在 `/data/` 下，`file_path` 指向外部絕對路徑。

---

## EH 並發限制器

Redis-based Global Semaphore：

| 設定 | 值 |
|------|-----|
| `EH_MAX_CONCURRENCY` | 2 |
| `EH_REQUEST_TIMEOUT` | 30 秒 |
| `EH_ACQUIRE_TIMEOUT` | 60 秒 |

流程：先查 Redis 快取（不佔 semaphore），快取未命中才 acquire semaphore 發外部請求。

---

## 測試基礎設施

| 層級 | 框架 | 執行命令 |
|------|------|---------|
| Backend | pytest + httpx AsyncClient + SQLite (shared cache) | `cd backend && python -m pytest` |
| Frontend | vitest + @testing-library/react | `cd pwa && npx vitest run` |

- Backend 測試設定：`backend/pytest.ini`
- Frontend 測試設定：`pwa/vitest.config.ts`（如有）

---

## 備份與 Migration

- **Alembic migration**：`backend/alembic.ini` + `backend/migrations/`
- **備份腳本**：`scripts/backup.sh`（PostgreSQL dump + gallery 檔案）
- **還原腳本**：`scripts/restore.sh`
