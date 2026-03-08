# Jyzrox — CLAUDE.md

個人圖庫管理平台。Docker Compose 自架服務。

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

## 網路架構

- Nginx 容器僅監聽 HTTP（port 80），**設計上透過外部反向代理（如 Caddy / Traefik / cloud LB）終止 TLS**
- 外部代理負責 HTTPS 憑證、HTTP→HTTPS 重導向
- `cookie_secure` 預設 `True`，在外部代理提供 HTTPS 時正常運作；純 HTTP 開發時需設 `COOKIE_SECURE=false`

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

---

## Multi-Agent 開發架構

使用 Claude Code 的 Agent 工具進行並行開發，適用於大規模健檢、重構、功能開發等任務。
核心原則：**每個 Agent 負責不重疊的檔案範圍**，避免寫入衝突。

### Main Orchestrator（Opus）角色

> ⚠️ **除非使用者特別指定，否則 Main Orchestrator 不直接寫代碼。** 所有代碼修改預設委派給對應的 Agent 執行。

Main Orchestrator 的職責：
1. **接收需求** — 理解用戶意圖，拆解任務
2. **啟動審查 Agent** — 並行派發 Explore Agent 收集報告
3. **規劃與分配** — 從報告提取問題，按檔案範圍分組，制定修改計畫
4. **啟動實施 Agent** — 將具體修改指令派發給對應 Agent（`mode=auto`）
5. **驗證結果** — 執行 build/test 確認改動正確
6. **彙報用戶** — 總結改動內容

Main Orchestrator **預設不做**（除非使用者明確要求）：
- ❌ 直接使用 Edit/Write 修改 `backend/`、`pwa/src/`、`db/`、`nginx/` 等代碼檔案
- ❌ 跳過 Agent 直接修 bug（即使是「小修改」也要委派）
- ✅ 可以修改 `CLAUDE.md`、memory 檔案等非代碼配置
- ✅ 使用者明確指示「你直接改」「不用開 agent」時，可直接寫代碼

### Agent 角色定義

| Agent | subagent_type | 職責 | 對應檔案範圍 |
|-------|---------------|------|-------------|
| Backend Architect | `backend-architect` | 後端架構審查、安全性、效能、代碼修改 | `backend/` 全部 |
| Frontend Architect | `frontend-architect` | 前端架構、UX、PWA、代碼修改 | `pwa/src/` 全部 |
| QA Tester | `qa-tester` | 測試覆蓋分析、測試計畫、撰寫測試 | `backend/tests/`, `pwa/src/__tests__/` |
| DevOps Engineer | `devops-engineer` | Docker/Nginx/部署/備份、配置修改 | `docker-compose.yml`, `nginx/`, `scripts/`, `db/` |
| Documentation Writer | `doc-writer` | 文檔審查與撰寫 | `*.md`, `docs/` |

### 並行開發原則

- **除非使用者特別指定，Main Orchestrator 只做規劃與協調，不直接寫代碼**
- 每個 Agent 負責不重疊的檔案範圍，避免寫入衝突
- 先啟動審查/研究 Agent（`subagent_type=Explore`），收集結構化報告
- 再啟動實施 Agent（`mode=auto`），根據報告修改代碼
- **審查與實施分兩輪，不在同一輪混用**

### 使用流程

```
Phase 1: 審查（5 Explore Agents 並行）
  → 各 Agent 輸出結構化報告（問題清單 + 改善建議）
  → Main Orchestrator 彙整為統一的健檢報告

Phase 2: 規劃（Main Orchestrator）
  → 從報告中提取 Critical/High 問題
  → 按檔案範圍分組，確保 Agent 間不衝突
  → 為每個 Agent 撰寫具體修改指令

Phase 3: 實施（N 個 Typed Agents 並行）
  → 使用對應的 subagent_type 啟動 Agent（mode=auto）
  → 每個 Agent 只修改分配到的檔案
  → Agent 完成後回報改動摘要

Phase 4: 驗證（Main Orchestrator）
  → Backend: pytest
  → Frontend: vitest + next build
  → Docker: docker compose build
  → 全面通過後才算完成，失敗則派發修復 Agent
```

### 測試基礎設施

| 層級 | 框架 | 執行命令 |
|------|------|---------|
| Backend | pytest + httpx AsyncClient + SQLite (shared cache) | `cd backend && python -m pytest` |
| Frontend | vitest + @testing-library/react | `cd pwa && npx vitest run` |

- Backend 測試設定：`backend/pytest.ini`
- Frontend 測試設定：`pwa/vitest.config.ts`（如有）

### 備份與 Migration

- **Alembic migration**：`backend/alembic.ini` + `backend/migrations/`
- **備份腳本**：`scripts/backup.sh`（PostgreSQL dump + gallery 檔案）
- **還原腳本**：`scripts/restore.sh`
