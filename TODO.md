# Jyzrox TODO

> 最後更新：2026-03-11

---

## P1 — 短期高價值

> 獨立功能，少依賴，能快速上線。

### 排程任務管理頁面（/scheduled-tasks）

> **現狀**：後端 `GET/PATCH/POST /api/scheduled-tasks` 已全部實作，
> 支援 library_scan / reconciliation / check_subscriptions 三個 cron job，
> 狀態存 Redis，可手動觸發。前端頁面與側邊欄入口尚未建立。

#### 前端
- [ ] `/scheduled-tasks` 頁面：列出所有排程任務卡片
  - 顯示：任務名稱、描述、cron 表達式、上次執行時間、上次狀態（成功/失敗/執行中）
  - 開關：啟用/停用（`PATCH /{id}` enabled）
  - cron 表達式內聯編輯（驗證格式後 PATCH）
  - 「立即執行」按鈕（`POST /{id}/run`）+ 執行中 loading 狀態
  - 失敗時顯示 last_error 展開區塊
- [ ] 側邊欄新增入口（`/scheduled-tasks`，圖示 `CalendarClock`）
- [ ] i18n keys（`scheduledTasks.*`）

---

### 去重系統（Tiered Dedup）

> **現狀**：Tier 0（SHA256 exact dedup）完整實作，CAS ref_count 管理正常。
> `blobs` 表已有 `width/height/file_size/phash_int/phash_q0~q3`，掃描基礎設施就位。
>
> **目標**：分層漸進式去重，預設只有 Tier 0 啟用，其餘需手動開啟。
> 低效能裝置不受影響；高效能裝置可逐層啟用。

#### 分層說明

| Tier | 名稱 | 預設 | 資源消耗 |
|------|------|------|---------|
| 0 | SHA256 精確去重 | 永遠開啟 | 零（匯入時同步） |
| 1 | pHash 相似掃描 | **關閉** | 輕量（純 DB） |
| 2 | Heuristic 分類 | **關閉** | 極輕量（純 metadata） |
| 3 | Deep Pixel Diff (OpenCV) | **關閉** | CPU 密集（P3 再做） |

#### 資料庫
- [ ] 新增 `blob_relationships` 表
  - `sha256_a / sha256_b`（`CHECK sha256_a < sha256_b`，`UNIQUE` pair，正規化排序）
  - `hamming_dist SMALLINT`（pHash 漢明距離 0–64）
  - `relationship TEXT`（`quality_conflict` / `variant` / `whitelisted`）
  - `suggested_keep TEXT`（heuristic 建議保留的 sha256）
  - `diff_type TEXT`（null / `compression_noise` / `localized_diff`，Tier 3 填寫）
  - `diff_score FLOAT`（OpenCV 分析分數，Tier 3 填寫）
  - `size_ratio FLOAT`（`file_size_a / file_size_b`）
  - `tier SMALLINT`（由哪層產生）
  - `reviewed BOOLEAN DEFAULT FALSE`
  - `created_at TIMESTAMPTZ DEFAULT now()`
- [ ] 遷移腳本

#### Config
- [ ] `core/config.py` 新增 dedup 設定欄位
  - `dedup_phash_enabled: bool = False`（Tier 1，預設關閉）
  - `dedup_phash_threshold: int = 10`（漢明距離閾值，0–64）
  - `dedup_heuristic_enabled: bool = False`（Tier 2，預設關閉）
  - `dedup_batch_size: int = 500`（每批掃描筆數）
  - `dedup_schedule: str = "0 3 * * *"`（排程，預設凌晨 3 點）

#### 後端 — Tier 1 pHash 掃描
- [ ] `services/dedup.py`：`scan_phash_pairs(batch_size, threshold)`
  - 四象限 pre-filter → Hamming distance 計算 → 寫入 `blob_relationships`
  - 已有 `whitelisted` pair 跳過，不重複插入
- [ ] `scheduled_tasks.py` 新增 `dedup_scan` task（`dedup_phash_enabled` 為 false 時自動 skip）
- [ ] `GET /api/dedup/stats`：總 pairs 數、待審查數、已白名單數

#### 後端 — Tier 2 Heuristic 分類
- [ ] `services/dedup.py`：`classify_relationships()`
  - 品質衝突：`width*height` 差 > 20% 或 `size_ratio > 2.0` → `quality_conflict`，填 `suggested_keep`（尺寸大/檔案大者）
  - 差分疑似：尺寸相同 且 `0.8 ≤ size_ratio ≤ 1.25` → `variant`，`suggested_keep = null`
- [ ] 作為 `dedup_scan_job` 後處理步驟（同一 job，受 `dedup_heuristic_enabled` 控制）

#### 後端 — 審查 API
- [ ] `routers/dedup.py`（新建，prefix `/api/dedup`）
  - `GET /review`：列出待審關係（可篩 relationship / reviewed，cursor 分頁）
  - `POST /review/{id}/keep`：Replace & Delete 低畫質副本
    1. `UPDATE images SET blob_sha256=suggested_keep WHERE blob_sha256=other`
    2. `decrement_ref_count(other_sha256)`
    3. `ref_count ≤ 0` → `os.unlink` CAS 實體檔 + `DELETE FROM blobs`
    4. rebuild affected gallery symlinks
  - `POST /review/{id}/whitelist`：標記白名單，掃描永久跳過此 pair
  - `DELETE /review/{id}`：略過（不白名單，只標 reviewed=true）
- [ ] `main.py` 註冊 router（`prefix="/api/dedup"`）
- [ ] Auth 保護所有端點

#### 前端
- [ ] `/dedup` 頁面（側邊欄入口，圖示 `ScanSearch`）
  - **設定區塊**（頁面頂部卡片）：
    - Tier 1 pHash 掃描：開關 + 漢明距離滑桿（0–20）
    - Tier 2 Heuristic 分類：開關（依賴 Tier 1，Tier 1 關閉時 disabled）
    - 排程 cron 表達式顯示（連結到 `/scheduled-tasks` 頁修改）
    - 「立即掃描」按鈕（觸發 `/scheduled-tasks` dedup_scan run）
    - 統計：已掃 X pairs，待審 Y 組，已解決 Z 組
  - **審查列表**（主區塊）：
    - 依 relationship 分類顯示（品質衝突 / 差分疑似）
    - 每組並排顯示兩張圖：解析度、檔案大小、pHash 距離
    - 品質衝突：高亮建議保留版（綠框），另一張預設標記刪除（紅框）
    - 差分疑似：中性呈現，兩張並排無建議
    - 操作按鈕：「刪除低畫質」（Replace & Delete）/ 「標為差分」（Whitelist）/ 「略過」
  - 空狀態：未啟用時顯示「開啟 Tier 1 開始掃描」引導提示
- [ ] 側邊欄新增入口（`/dedup`，圖示 `ScanSearch`）
- [ ] i18n keys（`dedup.*`）
- [ ] `api.ts` 新增 dedup 端點型別

---

### 大量下載

#### 後端
- [ ] 批次下載 API：接受標籤/作者/搜尋條件，列舉所有符合的 gallery
- [ ] 批次 enqueue 機制（避免一次灌入數千 job 壓垮 worker）
- [ ] 批次任務進度追蹤（Redis：總數/已完成/失敗）
- [ ] E-Hentai 標籤全下載（爬取搜尋結果所有頁 → 逐一 enqueue）
- [ ] Pixiv 作者全作品下載（取得作品列表 → 逐一 enqueue）
- [ ] 下載速率限制設定（避免被封 IP）

#### 前端
- [ ] 批次下載 UI 入口（從搜尋結果頁觸發）
- [ ] 批次任務儀表板（總進度、成功/失敗統計）
- [ ] 批次下載確認 dialog（預覽數量、預估大小）

---

## P2 — 中期功能（有依賴鏈）

> 需多階段實施或依賴較多。

### 即時狀態推送（WebSocket）

> **現狀**：下載佇列等核心狀態靠 SWR polling（每 3 秒一次）。WebSocket 基礎設施已存在（`/api/ws`），目前只用於系統警告推送。
>
> **目標**：Worker 完成/進度事件 → Redis pub/sub → WS handler 轉發前端，消除 polling。

#### 後端
- [ ] `worker/` 各 job function 完成/進度時發布 Redis 事件（`job:{id}:status`、`job:{id}:progress`）
- [ ] `routers/ws.py` 訂閱 Redis channel，將事件轉發至 WebSocket 連線
- [ ] 定義標準化 WebSocket 事件格式（`{ type: 'job_update', job_id, status, progress }`）

#### 前端
- [ ] `useDownloadQueue` 改為訂閱 WebSocket 事件，移除 3s polling
- [ ] 下載進度條改為即時更新（毫秒級）
- [ ] WS 斷線時自動 fallback 到 polling（`lib/ws.ts` 已有重連邏輯）

---

### 多人權限管理

#### 資料庫
- [ ] `users` 表新增 `role` 欄位（`admin` / `member` / `viewer`）
- [ ] 遷移腳本：現有使用者預設 `admin`
- [ ] `gallery_permissions` 表（gallery_id, user_id, permission_level）

#### 後端
- [ ] `core/auth.py` — `require_role(role)` dependency（檢查角色權限）
- [ ] 管理端點：列出使用者、修改角色、停用帳號
- [ ] Gallery 權限控制：私有/公開/指定使用者可見
- [ ] 下載/匯入操作的權限檢查（member 以上）
- [ ] 設定頁（credentials、system）限 admin

#### 前端
- [ ] 使用者管理頁（`/admin/users`）：列表、角色切換、停用
- [ ] Gallery 分享 UI：設定可見性、邀請使用者
- [ ] 角色不足時的 403 提示頁面
- [ ] 側邊欄根據角色隱藏管理入口

#### 分享與內容控制
- [ ] 分享連結：Gallery 產生公開短連結（token-based，可設過期時間）
- [ ] Gallery 可見性設定（私有 / 公開 / 指定使用者）
- [ ] 內容過濾：依 tag namespace 隱藏 gallery（家長控制 / R18 過濾）
- [ ] 過濾規則存入 `user_preferences` 或擴充 `blocked_tags` 表

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
> - 遷移成本最低：概念對應（Worker → Worker, job function → job function, cron → cron）
> - 備用方案：AsyncTasQ

- [ ] 安裝 SAQ，建立基礎 worker 設定（`worker/saq_worker.py`）
- [ ] 遷移 job functions（`download_job`, `import_job`, `tag_job`, `subscription_check`）
- [ ] 遷移 cron scheduling（subscription 定時檢查）
- [ ] 替換 `arq.create_pool` → SAQ queue（`core/redis_client.py`, enqueue 呼叫點）
- [ ] 更新 Docker entrypoint（`saq worker.saq_worker:settings`）
- [ ] 移除 arq 依賴 + `core/compat.py` monkey-patch
- [ ] 驗證：Python 3.14 環境下完整 worker pipeline 正常運行
- [ ] 可選：啟用 SAQ Web UI dashboard

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

### 語意搜尋（pgvector）

> **前提**：WD14 Tagger 微服務（`tagger/`）已建立，特徵提取基礎設施就位。
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

### 封存格式支援（ZIP / CBZ / EPUB / PDF）

> **現狀**：Jyzrox 的 import pipeline 只處理解壓後的平面檔案目錄，無法直接讀取封存格式。LANraragi、Kavita、Suwayomi 均以封存檔為一等公民。
>
> **目標**：支援 ZIP/CBZ 直接匯入並在線上閱讀；PDF/EPUB 作為延伸目標。

#### 後端
- [ ] `worker/importer.py`：偵測輸入為封存檔時自動解壓（`zipfile`/`rarfile`），後續流程不變
- [ ] 支援格式：`.zip`、`.cbz`（Phase 1）；`.cbr`（`.rar`，需 `rarfile` 或 `patool`）（Phase 2）
- [ ] PDF 支援：`pypdf` 或 `pdf2image` 逐頁提取為圖片，匯入 CAS（Phase 3）
- [ ] EPUB 支援：提取圖片頁面，忽略文字內容（Phase 3）
- [ ] `GET /api/import/browse` 檔案瀏覽器：顯示封存檔並允許直接匯入
- [ ] Download pipeline：`download_job` 完成後若產物為封存檔，自動觸發解壓流程

#### 前端
- [ ] Import Center：封存檔拖曳上傳入口（`POST /api/import/upload`）
- [ ] 匯入預覽：顯示封存內頁數與封面縮圖

### 漫畫系列結構（Series / Volume / Chapter）

> **現狀**：Gallery 為扁平結構，無父子關係。Kavita 與 Suwayomi 以 Series → Volume → Chapter 三層結構組織內容，支援連續閱讀與進度追蹤。
>
> **目標**：在現有 Gallery 模型上疊加可選的系列層，不破壞現有扁平使用模式。

#### 資料庫
- [ ] 新增 `series` 表：`id`, `title`, `title_jpn`, `cover_gallery_id`, `tags_array`, `created_at`
- [ ] `galleries` 表新增 `series_id FK`、`volume_num`、`chapter_num`、`chapter_title` 欄位（全部 nullable，保持向後相容）
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

### Plugin 系統完善

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

### DevOps / 基礎設施
- [ ] 集中式日誌（Loki + Grafana 或類似方案）
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

## 已完成（v0.1 歷史記錄）

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
- [x] 資料庫自動遷移機制（Alembic，8 個版本遷移）
- [x] 自動化 CI（GitHub Actions：lint + test + build）
- [x] 容器資源限制（全服務 `deploy.resources` 配置）
- [x] nginx `auth_request` 保護 `/media/` 路徑（subrequest auth + 快取）

### 測試
- [x] Backend 221 tests
- [x] Frontend 242 tests
- [x] WebSocket 斷線重連（3 秒自動重連，`lib/ws.ts`）
- [x] Redis 快取統計端點（`GET /api/system/cache`）

</details>
