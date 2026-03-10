Jyzrox

系統架構

Backend
FastAPI + SQLAlchemy (asyncpg) + ARQ

Frontend
Next.js 15 App Router (PWA)

Database
PostgreSQL 15 + Redis 7

Proxy
Nginx


Pipeline 架構

1. [完成] OnWeb Preview：直接瀏覽網站圖庫
   - E-Hentai：搜尋、收藏、熱門、gallery detail
   - Pixiv：推薦、排行、追蹤作者、作者頁面、illust detail

2. [完成] Downloader：
   - EH：自有原生引擎（EhClient，含 nl 重試、semaphore 並發控制）
   - Pixiv：原生 OAuth 下載器（4 phases 完整實作）
   - 其他：gallery-dl subprocess fallback
   - 來源自動偵測（URL domain routing，不需手動選擇來源）

3. [完成] Local Browser：本地圖庫瀏覽
   - 縮圖 grid、tag/rating 過濾、全文搜尋
   - 閱讀器：single / webtoon / double-page，touch + keyboard
   - 影片支援（mp4/webm inline playback）
   - 閱讀進度自動儲存（2s debounce）

4. [完成] Storage / DB：
   - CAS (Content-Addressable Storage) + symlinks
   - Library 路徑管理（多路徑、filesystem watcher、定時掃描）
   - Reconciliation job（DB/filesystem 一致性檢查）

5. [完成] Plugin 系統：
   - ABC-based plugin 架構（SourcePlugin, BrowsePlugin, TaggerPlugin）
   - URL-based routing，fallback 到 gallery-dl
   - 詳見 `backend/plugins/`（規劃文件已歸檔：plugin_architecture_plan.md）

6. [完成] i18n 抽象層：
   - `pwa/src/lib/i18n/` — `t()` 函數，所有 UI 文字透過 key 存取
   - 英文為基礎語言，其他語言 fallback 到英文

7. [完成] OPDS 支援：
   - `/opds` feed，支援 e-reader 客戶端（KOReader, Yomu 等）
   - Basic auth 認證

8. [完成] External API：
   - `/api/external/v1` — token 認證外部 API
   - 支援 Mihon 擴充套件整合

9. [部分完成] AI Train Export / Tag：
   - Kohya zip export 已完成（`/api/export`）
   - AI 自動打標（WD14）架構已建立，預設停用（`tag_model_enabled=false`）

------

未來計畫（尚未實作）:
- 多人權限管理（目前已有多帳號，尚無細粒度權限）
- 大量下載（e-hentai 特定標籤全部下載、Pixiv 作者全部下載的批次佇列 UI）
- 多國語言翻譯（i18n 抽象層已就緒，尚缺翻譯內容）
- 自訂 Booru / 第三方來源 plugin
