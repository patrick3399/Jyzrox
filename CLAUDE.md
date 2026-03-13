# Jyzrox — CLAUDE.md

個人圖庫管理平台。Docker Compose 自架服務。

> 詳細架構參考：`.claude/docs/architecture.md`（目錄結構、API Router、DB Schema、Worker Pipeline、前端規範、網路架構）

---

## 語言政策

| 範圍 | 語言 | 範例 |
|------|------|------|
| Git 追蹤的程式碼與文檔 | **English** | `backend/`、`pwa/src/`、`docs/`、`docker-compose.yml`、code comments、commit messages、PR descriptions |
| Claude workflow 檔案 | **繁體中文** | `CLAUDE.md`、`.claude/agents/*.md`、`.claude/skills/`、`TODO.md`、memory files |

- 程式碼內的變數名、函式名、docstring、error message → English
- i18n 翻譯檔 (`pwa/src/lib/i18n/`) 各語言照常
- Git commit message → English

---

## 技術棧

| 層級 | 技術 |
|------|------|
| Backend API | FastAPI + SQLAlchemy (asyncpg) + ARQ |
| Frontend | Next.js 16 App Router (PWA) |
| DB | PostgreSQL 18 + Redis 8 |
| 反向代理 | Nginx |
| 下載引擎 | Plugin system + gallery-dl fallback |

---

## 認證機制

- httpOnly cookie：`vault_session = {user_id}:{token}`
- Redis key：`session:{user_id}:{token}`，TTL 30 天
- FastAPI dependency：`from core.auth import require_auth`
- **所有需要保護的端點都必須加 `_: dict = Depends(require_auth)`**
- 登入流程：`/login` → POST `/api/auth/login` (`{username, password}`) → 設定 cookie
- 初次設定：`/setup` → POST `/api/auth/setup`（僅在無用戶時可用）
- 前端 proxy (`proxy.ts`) 自動將未登入請求導向 `/login`

### 角色權限

三級階層式角色，高級自動繼承低級權限：

| 角色 | 等級 | 說明 |
|------|------|------|
| `admin` | 3 | 系統設定、使用者管理、登入資訊、排程任務、重複偵測 |
| `member` | 2 | 下載、匯入匯出、訂閱、圖庫編輯 |
| `viewer` | 1 | 瀏覽、搜尋、歷史紀錄、收藏夾（唯讀） |

- `require_auth()` 回傳 `{"user_id": int, "role": str}`
- `require_role("admin")` 建立角色檢查 dependency（自動包含更高等級）
- Role 從 Redis session metadata 讀取，改 role 後需重新登入生效

---

## 部署操作

> 部署相關 skill 定義在 `.claude/skills/deploy/` 和 `.claude/skills/preflight/`

### 更新服務
```bash
docker compose build api worker pwa
docker compose up -d api worker pwa
# ⚠️ 重要：容器重建後 nginx 需 reload，否則 502（IP 變更）
docker compose exec nginx nginx -s reload

# 若需 AI tagging 功能：
docker compose --profile tagging build
docker compose --profile tagging up -d
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

需要角色限制時使用 `require_role`：
```python
from core.auth import require_role

_admin = require_role("admin")
_member = require_role("member")

@router.post("/admin-action")
async def admin_only(auth: dict = Depends(_admin)):
    ...

@router.post("/member-action")
async def member_up(auth: dict = Depends(_member)):
    ...
```

### Python 版本限制：目前鎖定 3.13
arq==0.27.0 使用已移除的 `asyncio.get_event_loop()`，Python 3.14+ 會 crash。待 arq 上游修復後才能升級。

### WD14 Tagger 獨立容器
AI tagging 已拆為獨立微服務（`tagger/`），透過 `--profile tagging` 按需啟動：
```bash
# 啟動 tagger
docker compose --profile tagging up -d

# 檢查狀態
curl http://localhost:8100/health
```
Worker 透過 HTTP 呼叫 tagger，tagger 離線時 tag_job 自動 skip。
設定：`TAGGER_URL`（default `http://tagger:8100`）、`TAGGER_TIMEOUT`（default 30s）。

### Tailwind 4 CSS-first 配置
- 無 `tailwind.config.ts`，所有配置在 `globals.css`
- 顏色註冊用 `@theme inline`，暗色模式用 `@custom-variant dark`
- CSS 變數使用 hex 格式（非 space-separated RGB）

### React 19 useRef 必須傳初始值
```tsx
// ✅ 正確
const ref = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

// ❌ React 19 會報錯
const ref = useRef<ReturnType<typeof setTimeout>>()
```

### Next.js 16 測試須 mock next/navigation
測試中使用 `useRouter()` / `useSearchParams()` 須加 mock，否則 throw `invariant expected app router to be mounted`：
```ts
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
```

### 前端 UI 文字必須使用 i18n 抽象層

所有使用者可見的 UI 文字（按鈕、標籤、placeholder、toast、錯誤訊息、aria-label）都必須透過 `t()` 函數：

```tsx
import { t } from '@/lib/i18n'

// ✅ 正確
<button>{t('settings.save')}</button>
<input placeholder={t('settings.searchPlaceholder')} />
toast.success(t('common.saved'))

// ❌ 禁止
<button>Save</button>
<input placeholder="Search..." />
toast.success('Saved')
```

**例外**（不需要 `t()`）：
- 專有名詞 / 品牌名：`"E-Hentai"`, `"Pixiv"`, `"Next.js"`, `"PostgreSQL"`, `"Jyzrox"`
- 版本號、數字、技術識別符：`"0.1"`, `"X-API-Token"`, `"/api/external/v1/status"`
- CSS class、HTML attribute value

**新增 UI 文字時**：
1. 在 `pwa/src/lib/i18n/en.ts` 加入英文 key（其他語言自動 fallback 到英文）
2. Key 命名慣例：`{section}.{description}`，如 `browse.failedLoadResults`、`settings.createToken`
3. 帶參數用 `{param}` 語法：`t('browse.pageN', { page: '5' })`

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
