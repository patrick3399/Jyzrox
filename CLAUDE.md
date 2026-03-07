# Jyzrox — CLAUDE.md

個人圖庫管理平台，rev 2.0。Docker Compose 自架服務。

---

## 技術棧

| 層級 | 技術 |
|------|------|
| Backend API | FastAPI + SQLAlchemy (asyncpg) + ARQ |
| Frontend | Next.js 15 App Router (PWA) |
| DB | PostgreSQL 15 + Redis 7 |
| 反向代理 | Nginx |
| 下載引擎 | gallery-dl (subprocess) |

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

## 認證機制

- httpOnly cookie：`vault_session = {user_id}:{token}`
- Redis key：`session:{user_id}:{token}`，TTL 30 天
- FastAPI dependency：`from core.auth import require_auth`
- **所有需要保護的端點都必須加 `_: dict = Depends(require_auth)`**
- 登入流程：`/login` → POST `/api/auth/login` (`{username, password}`) → 設定 cookie
- 初次設定：`/setup` → POST `/api/auth/setup`（僅在無用戶時可用）
- 前端 middleware (`middleware.ts`) 自動將未登入請求導向 `/login`

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

## 部署操作

### 更新服務
```bash
# 重新 build 並重啟（不影響 postgres/redis）
docker compose build api worker pwa
docker compose up -d api worker pwa

# ⚠️ 重要：容器重建後 nginx 需 reload，否則 502（IP 變更）
docker compose exec nginx nginx -s reload
```

### 查看日誌
```bash
docker compose logs api --tail=50
docker compose logs worker --tail=50
docker compose logs nginx --tail=30
```

### 容器內 UID
- prod：`1042:1042`（appuser）
- dev override：`1000:1000`（`docker-compose.override.yml`）

---

## 常見問題

### 502 Bad Gateway
nginx 在 api 容器重建後快取了舊 IP：
```bash
docker compose exec nginx nginx -s reload
```

### 新增 router 後記得在 main.py 註冊
```python
from routers import your_router
app.include_router(your_router.router, prefix="/api/xxx")
```

### 修改代碼後務必重建 Docker 容器
代碼修改完成後，必須重新 build 並重啟相關容器，否則改動不會生效：
```bash
docker compose build api worker pwa
docker compose up -d api worker pwa
docker compose exec nginx nginx -s reload
```

### 所有保護端點必須有 auth
```python
from fastapi import Depends
from core.auth import require_auth

@router.get("/")
async def endpoint(_: dict = Depends(require_auth)):
    ...
```
