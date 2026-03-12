# Jyzrox TODO

> 最後更新：2026-03-13

---

## P1 — 短期高價值

> 獨立功能，少依賴，能快速上線。

### Subscription 擴展 — 大量下載

> **策略**：不另建批次下載系統，擴展現有 Subscription 架構。
> X/Twitter 已驗證可行（generic fallback → gallery-dl 爬全頁），Pixiv 首次 check 時 `last_item_id=None` 也會回傳全部作品。
> 核心缺口：EH 沒有 `Subscribable` 實作，且 generic fallback 無增量追蹤。

#### ~~Phase 1：EH Subscribable 實作~~ ✅ Done
- [x] `plugins/builtin/ehentai/_subscribe.py`：實作 `check_eh_new_works()` — EhClient.search() 逐頁爬取 → gid 邊界比對 → 回傳 `list[NewWork]`
- [x] EH `EhSourcePlugin` 加入 `Subscribable` protocol 實作（`check_new_works()` 委派）
- [x] 支援訂閱類型：uploader 頁面（`/uploader/xxx`）、標籤搜尋 URL（`?f_search=tag:xxx`）、tag 頁面（`/tag/xxx`）
- [x] 增量追蹤：以 gallery gid 作為 `last_item_id`，`gid <= last_known` 邊界停止
- [x] 處理 EH 分頁：最多 10 頁、3s 間隔，首次 check 只取一頁
- [x] `_extract_source_id()` 支援 EH/ExH URL 解析（f_search / tag / uploader），`unquote()` 正確解碼
- [x] `EhClient.search()` 等 4 處 set 去重改為 `dict.fromkeys()` 保序
- [x] 30 個單元測試覆蓋

#### Phase 2：批次 enqueue 保護
- [ ] 節流 enqueue：首次全量下載可能產生數百個 job，加入 enqueue 間隔（可設定 delay）
- [ ] Subscription 新增 `total_enqueued` / `total_completed` 欄位，追蹤批次進度
- [ ] Redis key `subscription:progress:{sub_id}` — 即時統計（總數/已完成/失敗）
- [ ] Worker enqueue 時推送 WebSocket 進度事件

#### Phase 3：前端強化
- [ ] Subscription 建立時偵測 EH URL → 預覽「此訂閱約有 N 本 gallery」（dry-run check）
- [ ] Subscription 卡片顯示批次進度（進度條：已完成/總數）
- [ ] 首次全量下載確認 dialog（「將下載約 N 本，是否繼續？」）
- [ ] 從 EH 瀏覽器搜尋結果頁「一鍵訂閱」按鈕（帶入搜尋 URL）

#### 獨立項目
- [x] ~~下載速率限制設定：per-site concurrency / delay_ms~~ → 移至「統一限速控制」完成
- [x] ~~時段排程解鎖~~ → 移至「統一限速控制」完成
- [ ] Hentai@Home 支援：EH plugin 偵測 H@H 可用時自動解鎖限速（或手動覆蓋）

> ✅ 已套用：`enqueue` 端點已加 `require_role("member")`，job 列表依角色篩選

---

## P2 — 中期功能（有依賴鏈）

> 需多階段實施或依賴較多。

### 應用內 Log Viewer

> 輕量級方案：Python logging handler 寫入 DB / Redis List，前端可查詢與篩選。不取代 P3 的 Loki/Grafana，兩者定位不同（應用內快速 debug vs. 長期 infra 監控）。

#### 後端
- [ ] `system_logs` 表或 Redis List（TTL 7 天）：level、source（api/worker/plugin）、message、timestamp
- [ ] Python logging handler：將 WARNING 以上寫入儲存層，支援 log level 過濾
- [ ] `GET /api/system/logs`：查詢端點（level filter、source filter、時間範圍、分頁），建立時就加 `require_auth`
- [ ] 自動清理：cron job 刪除超過設定天數的紀錄（預設 7 天，可設定）

#### 前端
- [ ] `/logs` 頁面（或整合至 `/settings`）：Log 列表（level badge、source、timestamp、message）
- [ ] 篩選工具列：level 多選、source 多選、時間範圍
- [ ] 自動捲動到最新 / 暫停捲動切換
- [ ] Log 保留天數設定

> ✅ 已套用：建立時直接使用 `require_role("admin")`

---

### Gallery 分享與可見性控制

> 依賴：多人權限 ✅ 已完成
> 基礎設施：`galleries.visibility` 欄位 + `gallery_visibility_filter()` helper 已存在

- [x] Gallery 基礎可見性欄位（`galleries.visibility` default 'public'，`created_by_user_id`，GIN index）
- [x] 後端可見性過濾 helper（`core/gallery_access.py`，`gallery_visibility_filter()`）
- [ ] `gallery_permissions` 表（gallery_id, user_id, permission_level）
- [ ] Gallery 可見性設定 API（PATCH visibility：私有 / 公開 / 指定使用者）
- [ ] Gallery 分享 UI：設定可見性、邀請使用者
- [ ] 分享連結：Gallery 產生公開短連結（token-based，可設過期時間）
- [ ] 內容過濾：依 tag namespace 隱藏 gallery（R18 過濾），存入 `user_preferences`

---

## P3 — 長期 / 按需

> 非核心功能、大型重構、按需啟動。

### arq → SAQ 遷移

> **背景**：arq 0.27.0 使用已移除的 `asyncio.get_event_loop()`，Python 3.14+ crash。上游 PR #509 長期未合併，專案已停滯。目前靠 `core/compat.py` monkey-patch 撐住，但非長久之計。
>
> **選定方案**：[SAQ](https://github.com/tobymao/saq)（Simple Async Queue）
> - 同為 asyncio-native + Redis backend，API 風格接近 arq
> - 內建 Web UI dashboard、cron scheduling、heartbeat
> - 活躍維護（2024–2025 持續發版）、Python 3.14 相容
> - 備用方案：AsyncTasQ

- [ ] 安裝 SAQ，建立基礎 worker 設定（`worker/saq_worker.py`）
- [ ] 遷移 job functions（`download_job`, `import_job`, `tag_job`, `subscription_check`）
- [ ] 遷移 cron scheduling（subscription 定時檢查）
- [ ] 替換 `arq.create_pool` → SAQ queue（`core/redis_client.py`, enqueue 呼叫點）
- [ ] 更新 Docker entrypoint（`saq worker.saq_worker:settings`）
- [ ] 移除 arq 依賴 + `core/compat.py` monkey-patch
- [ ] 驗證：Python 3.14 環境下完整 worker pipeline 正常運行
- [ ] 可選：啟用 SAQ Web UI dashboard

---

### PWA 離線儲存

> 讓使用者可將指定 gallery 標記為「離線可用」，SW 預先快取圖片，斷網時仍可閱讀。
>
> **限制**：Nginx `/media/` 需 auth（subrequest），SW 攔截需帶 httpOnly cookie，iOS Safari PWA Storage 配額約 50MB，需實作配額管理與 LRU 淘汰。
>
> **依賴**：多人權限 ✅ 已完成，`offline_galleries` 表含 `user_id` 支援 per-user 離線清單。

#### 後端
- [ ] `GET /api/library/galleries/{id}/offline-manifest`：回傳 gallery 所有圖片 URL 清單（供 SW 預快取）
- [ ] `offline_galleries` 表：`user_id`、`gallery_id`、`cached_at`、`size_bytes`

#### 前端（PWA / Service Worker）
- [ ] Gallery detail 頁新增「離線儲存」按鈕（觸發 SW 預快取）
- [ ] SW：攔截 `/media/` 請求，快取策略 Cache-First（離線） / Network-First（在線）
- [ ] 離線 gallery 列表頁（`/offline`）：顯示已快取 gallery 及佔用空間
- [ ] 配額管理：顯示已用空間，LRU 淘汰舊快取，支援手動清除

---

### S3 儲存抽象層

> **現狀**：CAS 層直接使用本機檔案系統（`os.link`、`Path`，綁定 `/data/cas/`）。
>
> **目標**：抽象 `StorageBackend` interface（local / S3-compatible），支援 MinIO、Cloudflare R2、AWS S3。個人用途目前不需要，NAS 搬遷或多節點部署時啟動。

- [ ] 定義 `StorageBackend` ABC：`put(sha256, data)`, `get(sha256)`, `exists(sha256)`, `delete(sha256)`, `link(sha256, dest)`
- [ ] `LocalStorageBackend`：封裝現有 `os.link` / Path 邏輯（zero-regression 重構）
- [ ] `S3StorageBackend`：boto3/aiobotocore，支援任意 S3-compatible endpoint
- [ ] CAS 層（`worker/importer.py`, `worker/reconciliation.py`）改為注入 `StorageBackend`
- [ ] Nginx `/media/` 靜態服務配合：local 繼續直接 serve，S3 改為簽名 URL redirect
- [ ] 設定欄位：`storage_backend`（`local` / `s3`）、`s3_endpoint`、`s3_bucket`、`s3_access_key`、`s3_secret_key`

---

### 語意搜尋（pgvector）

> **前提**：WD14 Tagger 微服務（`tagger/`）已建立 ✅，特徵提取基礎設施就位。
>
> **目標**：CLIP / WD14 特徵向量存入 `pgvector`，實現「以圖搜圖」與「文字語意搜 gallery」。

- [ ] PostgreSQL 啟用 `pgvector` extension（`db/init.sql` 或新 migration）
- [ ] `blobs` 表新增 `embedding vector(512)` 欄位
- [ ] `tagger/app.py` 新增 `/embed` 端點：回傳 CLIP/WD14 特徵向量（不只是 tag 列表）
- [ ] `worker/tagging.py` `tag_job` 完成後寫入 embedding 到 `blobs.embedding`
- [ ] 後端搜尋端點新增 `semantic_query` 參數（`GET /api/library/galleries?semantic=...`）
- [ ] 搜尋邏輯：文字 query → embedding → `<=>` cosine distance 排序
- [ ] 前端 Library 搜尋列新增「語意搜尋」模式切換
- [ ] 以圖搜圖：上傳圖片 → 提取 embedding → 找最相似 gallery

---

### 封存格式支援（ZIP / CBZ / EPUB / PDF）

> **現狀**：Jyzrox 的 import pipeline 只處理解壓後的平面檔案目錄，無法直接讀取封存格式。
>
> **目標**：支援 ZIP/CBZ 直接匯入並在線上閱讀；PDF/EPUB 作為延伸目標。

#### 後端
- [ ] `worker/importer.py`：偵測輸入為封存檔時自動解壓（`zipfile`/`rarfile`），後續流程不變
- [ ] 支援格式：`.zip`、`.cbz`（Phase 1）；`.cbr`（需 `rarfile` 或 `patool`）（Phase 2）
- [ ] PDF 支援：`pypdf` 或 `pdf2image` 逐頁提取為圖片（Phase 3）
- [ ] EPUB 支援：提取圖片頁面，忽略文字內容（Phase 3）
- [ ] `GET /api/import/browse` 檔案瀏覽器：顯示封存檔並允許直接匯入
- [ ] Download pipeline：`download_job` 完成後若產物為封存檔，自動觸發解壓流程

#### 前端
- [ ] Import Center：封存檔拖曳上傳入口（`POST /api/import/upload`）
- [ ] 匯入預覽：顯示封存內頁數與封面縮圖

---

### 漫畫系列結構（Series / Volume / Chapter）

> **現狀**：Gallery 為扁平結構，無父子關係。
>
> **目標**：在現有 Gallery 模型上疊加可選的系列層，不破壞現有扁平使用模式。

#### 資料庫
- [ ] 新增 `series` 表：`id`, `title`, `title_jpn`, `cover_gallery_id`, `tags_array`, `created_at`
- [ ] `galleries` 表新增 `series_id FK`、`volume_num`、`chapter_num`、`chapter_title`（全部 nullable）
- [ ] 遷移腳本

#### 後端
- [ ] `GET /api/library/series`：系列列表（含封面、章節數、總頁數）
- [ ] `GET /api/library/series/{id}`：系列詳情 + 章節列表（依 volume/chapter 排序）
- [ ] Gallery 編輯 API：支援指定 `series_id`、`volume_num`、`chapter_num`
- [ ] Reader API：`next_chapter` / `prev_chapter` 跨 gallery 連續閱讀端點

#### 前端
- [ ] `/series` 頁面：系列列表（封面格狀顯示）
- [ ] `/series/[id]` 頁面：系列詳情，章節列表，「從頭閱讀」按鈕
- [ ] Gallery detail 頁：可選指定所屬系列與章節號
- [ ] Reader：章節末尾「下一章」跳轉（呼叫 `next_chapter` 端點）

---

### Plugin 系統完善

> ✅ 多人權限已完成。Plugin enable/disable/configure 端點建立時直接使用 `require_role("admin")`。

#### 核心架構
- [ ] Plugin 介面定義（Python ABC）：`on_download`, `on_import`, `on_tag` hooks
- [ ] Plugin 載入器：掃描 `plugins/` 目錄，動態載入
- [ ] Plugin 設定 schema（每個 plugin 可宣告自己的設定欄位）
- [ ] Plugin 生命週期管理（enable/disable/configure）

#### 內建 Plugin（驗證架構）
- [ ] 通知 Plugin：下載完成時發送 Telegram/Discord webhook
- [ ] 自訂 metadata Plugin：從檔名/路徑萃取額外 tags

#### 管理介面
- [ ] `/settings/plugins` 頁面：列出已安裝 Plugin
- [ ] Plugin 啟用/停用開關
- [ ] Plugin 設定表單（動態生成）

---

### DevOps / 基礎設施

- [ ] 集中式日誌（Loki + Grafana）— P3 重量級方案，與 P2 應用內 Log Viewer 並行不衝突
- [ ] Docker image 瘦身：檢查 layer 大小，移除不必要依賴
- [ ] 生產環境 HTTPS 配置指南（Let's Encrypt + Nginx）

### 測試 / 品質

- [ ] AI tagging 端對端測試（mock ONNX model）
- [ ] CAS 儲存壓力測試（大量重複檔案去重驗證）
- [ ] Import 大量檔案效能測試（1000+ 圖片單次匯入）
- [ ] 社群貢獻翻譯指南文件

---

## 擱置中

> 需要特定環境或硬體才能進行，暫不排入。

- [ ] OPDS 實際 client 測試（Panels iOS / KOReader / Chunky）— 需要實體裝置
- [ ] AI Tagging 測試 `TAG_MODEL_ENABLED=true` 完整流程（模型下載→推理→DB 寫入）— 需要 ONNX runtime + 模型
- [ ] Mihon Extension 編譯 + 實機測試（gallery 列表、搜尋、篩選、閱讀）— 需要 Android 裝置

---

## 已完成

<details>
<summary>展開已完成項目</summary>

### 安全
- [x] CSRF protection（double-submit cookie pattern）
- [x] Rate limiting 全端點覆蓋
- [x] 檔案上傳 MIME magic byte 驗證

### 功能
- [x] E-Hentai 瀏覽器（搜尋、排行榜、收藏夾、圖片代理）
- [x] 下載引擎（gallery-dl + EH 自有引擎，download→import→thumbnail pipeline）
- [x] 下載來源自動偵測（移除手動 source 選擇）
- [x] 本地圖庫瀏覽（GIN 索引、cursor 分頁、封面縮圖）
- [x] Reader（單頁/瀑布/雙頁模式，進度同步）
- [x] CAS 儲存（SHA256 去重、hardlink、ref count）
- [x] Import Center（手動/自動匯入、重掃、監控、資料夾管理）
- [x] Tag 系統（別名、蘊含、翻譯、黑名單）
- [x] Kohya ZIP 匯出
- [x] WD14 AI Tagger 實作（待啟用）
- [x] pHash 相似圖搜尋
- [x] 搜尋排序（前後端）
- [x] Saved Searches（桌面+手機）
- [x] Stale session 修復

### Pixiv 全功能
- [x] Phase 1：Client + Router（pixivpy3 async 包裝、搜尋/詳情/代理端點、Redis 快取）
- [x] Phase 2：作者追蹤系統（followed_artists 表、追蹤 API、Worker cron 定時檢查）
- [x] Phase 3：原生下載器（pixiv_downloader.py、worker 整合、取代 gallery-dl）
- [x] Phase 4：前端頁面（搜尋/詳情/作者/追蹤管理頁面、導航整合）

### 效能
- [x] Virtual Scrolling（Library / Browse / History 頁面）

### Settings UI
- [x] 功能開關統一管理（CSRF / Rate Limiting / OPDS / External API / AI Tagging / 下載來源）
- [x] Security / Features 分區

### 後端 i18n
- [x] API 錯誤訊息 i18n + Accept-Language 自動偵測
- [x] Tag 名稱翻譯

### AI Tagging 前端
- [x] Gallery detail 頁顯示 AI 標籤（含信心度）
- [x] 「重新標記」按鈕整合到 Gallery detail
- [x] 標籤信心度篩選 UI（滑桿或閾值設定）

### i18n
- [x] 四語系（en/zh-TW/ja/ko）+ 簡體中文（zh-CN）
- [x] 韓文翻譯補齊缺失 keys
- [x] 使用者 locale 偏好存入 DB
- [x] 日期/數字格式化根據 locale
- [x] 複數形式支援

### PWA
- [x] Service Worker 自動版本管理 + 更新提示 UI
- [x] `manifest.json` share_target 宣告
- [x] Share Target 落地頁 + 一鍵下載
- [x] `POST /api/download/quick` 簡化端點
- [x] 離線時排隊（SW 快取分享請求，上線後補發）
- [x] Gallery 列表 infinite scroll + 縮圖懶載入

### External API / OPDS
- [x] OPDS 全端點（root/all/recent/favorites/search/gallery + OpenSearch + Basic Auth）
- [x] External API galleries/images/tags + download trigger + rate limiting

### DevOps
- [x] Docker 雙網路隔離
- [x] Nginx healthcheck
- [x] Multi-stage Dockerfile
- [x] backup/restore 腳本
- [x] Worker max_jobs + LOG_LEVEL 環境變數
- [x] 資料庫自動遷移機制（Alembic，baseline 0001 合併單一版本）
- [x] 自動化 CI（GitHub Actions：lint + test + build）
- [x] 容器資源限制（全服務 `deploy.resources` 配置）
- [x] nginx `auth_request` 保護 `/media/` 路徑（subrequest auth + 快取）

### 測試
- [x] Backend 221 tests
- [x] Frontend 242 tests
- [x] WebSocket 斷線重連（3 秒自動重連，`lib/ws.ts`）
- [x] Redis 快取統計端點（`GET /api/system/cache`）

### 即時狀態推送（WebSocket）
- [x] Worker 進度/狀態事件 → Redis pub/sub → WS handler → 前端即時更新
- [x] polling 降為斷線 fallback
- [x] Nginx 下載端點限流分流（jobs/stats 用 api_zone 30r/s，enqueue 用 download_zone 2r/s）

### 排程任務管理（v0.3）
- [x] `/scheduled-tasks` 頁面（任務卡片、cron 內聯編輯、啟用/停用、立即執行、last_error 展開）
- [x] 側邊欄 `CalendarClock` 入口
- [x] i18n `scheduledTasks.*` keys

### 去重系統 Tiered Dedup（v0.3）
- [x] `blob_relationships` 表（hamming_dist / relationship / suggested_keep / diff_score / tier / reviewed）
- [x] Tier 1 pHash 掃描（四象限 pre-filter → Hamming distance → `blob_relationships`）
- [x] Tier 2 Heuristic 分類（quality_conflict / variant，自動填 suggested_keep）
- [x] Tier 3 OpenCV pixel-diff 驗證（needs_t3 → quality_conflict / resolved）
- [x] `GET /api/dedup/stats`、`GET /api/dedup/review`、`POST /keep`、`POST /whitelist`、`DELETE /{id}`
- [x] scan/start、scan/stop、scan/progress 端點
- [x] Dedup config 欄位（phash_enabled / threshold / heuristic_enabled / opencv_enabled / batch_size / schedule）
- [x] `/dedup` 前端頁面（設定卡片、審查列表、並排圖片、操作按鈕、空狀態引導）
- [x] 側邊欄 `ScanSearch` 入口，i18n `dedup.*` keys，`api.ts` 型別

### 下載 Soft-Pause（v0.3）
- [x] EH / Pixiv plugin 下載支援 soft-pause（`PATCH /api/download/jobs/{id}` action=pause/resume）
- [x] Pause：Redis `download:pause:{job_id}` key → downloader poll → 正在傳輸的圖完成後才暫停
- [x] Resume：刪除 Redis key → 繼續下載
- [x] gallery-dl 繼續使用 SIGSTOP / SIGCONT（雙路徑邏輯）

### 多人權限 RBAC（v0.4）
- [x] 三級角色：admin / member / viewer（階層式，高級繼承低級權限）
- [x] `require_role()` factory dependency（`core/auth.py`）
- [x] `read_progress` per-user 隔離（composite PK `(user_id, gallery_id)`）
- [x] `download_jobs` per-user 歸屬（`user_id` FK + 列表篩選）
- [x] 全端點 RBAC 保護（settings/tag/dedup/scheduled-tasks/download/import/export/subscriptions）
- [x] 使用者管理 CRUD（`/api/users`，admin only）
- [x] 使用者管理頁面（`/admin/users`）
- [x] 403 Forbidden 頁面（`/forbidden`）
- [x] 側邊欄/底部導航依角色過濾
- [x] i18n 五語系支援（en/zh-TW/zh-CN/ja/ko）

### 安全強化（v0.5）
- [x] HMAC session signing + auth hardening + audit logging scaffold

### 統一限速控制（v0.5）
- [x] `SiteRateConfig` 設定結構（Redis-backed）：per-site concurrency、delay_ms、時段排程
- [x] `GET/PATCH /api/settings/rate-limits`：讀取與更新限速設定（admin only）
- [x] `POST /api/settings/rate-limits/override`：手動全速解鎖
- [x] 時段排程 cron job（`rate_limit_schedule_job`）：定時評估排程視窗，寫入/移除 Redis flag
- [x] `/settings` 下載限速分區 UI：per-site concurrency 滑桿、delay 輸入、排程設定、手動解鎖按鈕
- [x] i18n 五語系支援

### EH Subscribable（v0.6）
- [x] `check_eh_new_works()` 增量檢查（gid 邊界、分頁、use_ex 決策鏈）
- [x] `EhSourcePlugin` 實作 Subscribable protocol（自動偵測註冊）
- [x] `_extract_source_id()` 支援 EH URL（f_search / tag / uploader + percent-decode）
- [x] `EhClient` 搜尋結果保序修正（`dict.fromkeys`）
- [x] 30 個單元測試

</details>
