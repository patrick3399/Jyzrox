# Jyzrox TODO

> 最後更新：2026-03-10

---

## P0 — 安全 + 已完成功能驗證

> 立即處理：安全漏洞與已實作功能的測試驗證。

### 安全
- [x] CSRF protection（目前 cookie-based auth 無 CSRF token）
- [ ] Rate limiting 全端點覆蓋（目前僅 external API 有）

### Service Worker 版本管理
- [ ] 自動版本管理 — build 時注入 hash 或時間戳到 `CACHE_NAME`
- [ ] SW 更新提示 UI（偵測到新版本時提示使用者重整）

### OPDS 端點測試（HTTP Basic Auth）
- [ ] `GET /opds/` — Root navigation feed 回傳有效 Atom XML，包含 all/recent/favorites/search 四個 entry
- [ ] `GET /opds/all` — 回傳所有 gallery，驗證分頁（`?page=0&limit=5`），確認 `<link rel="next">` 存在
- [ ] `GET /opds/all?page=1` — 第二頁回傳不同 gallery，確認 `<link rel="previous">` 存在
- [ ] `GET /opds/recent` — 回傳最近 50 個 gallery，無分頁連結
- [ ] `GET /opds/favorites` — 僅回傳 `favorited=true` 的 gallery
- [ ] `GET /opds/search?q=關鍵字` — title ILIKE 搜尋結果正確
- [ ] `GET /opds/opensearch.xml` — 回傳有效 OpenSearch descriptor，template URL 正確
- [ ] `GET /opds/gallery/{id}` — 回傳 OPDS-PSE 頁面列表，每頁有 `pse:index`、image link、thumbnail link
- [ ] 無 Authorization header → 401 + `WWW-Authenticate: Basic realm="Jyzrox OPDS"` header
- [ ] 錯誤密碼 → 401
- [ ] nginx `auth_request` 用 Basic Auth 存取 `/media/cas/` 和 `/media/thumbs/` → 200
- [ ] 實際 OPDS client 測試（Panels iOS / KOReader / Chunky）連線瀏覽 + 圖片載入

### External API 增強測試（X-API-Token Auth）
- [ ] `GET /api/external/v1/galleries/{id}/images` — 回傳含 `file_url` 和 `thumb_url` 欄位
- [ ] `GET /api/external/v1/galleries/{id}/images/{page}/file` — 回傳正確圖片二進位（Content-Type 正確）
- [ ] 圖片不存在 → 404
- [ ] `GET /api/external/v1/galleries?q=test` — title 搜尋過濾正確
- [ ] `GET /api/external/v1/galleries?favorited=true` — 僅回傳收藏 gallery
- [ ] `GET /api/external/v1/galleries?min_rating=3` — 僅回傳 rating ≥ 3 的 gallery
- [ ] 多參數組合：`?q=test&favorited=true&min_rating=3&source=ehentai` — 正確 AND 過濾

### Mihon Extension 測試
- [ ] `./gradlew assembleDebug` 編譯通過
- [ ] 安裝到 Android 裝置/模擬器，Mihon 偵測到 Jyzrox 擴充
- [ ] 設定 Server URL + API Token 後，Popular 頁面載入 gallery 列表
- [ ] 搜尋功能：輸入關鍵字回傳正確結果
- [ ] Filter 測試：Source / Rating / Favorites 各篩選功能正常
- [ ] Gallery detail 顯示正確 metadata（title、author、tags、頁數）
- [ ] Chapter list 回傳 1 個 chapter
- [ ] Page list 載入完整圖片列表，圖片正常顯示
- [ ] 無 Token / 錯誤 Token → 適當錯誤提示

---

## P1 — 短期高價值

> 獨立功能，少依賴，能快速上線帶來明顯效果。

### AI Tagging 上線
- [ ] 測試 `TAG_MODEL_ENABLED=true` 完整流程（模型下載→推理→DB 寫入）
- [ ] 前端：Gallery detail 頁顯示 AI 標籤（含信心度）
- [ ] 前端：「重新標記」按鈕整合到 Gallery detail
- [ ] 標籤信心度篩選 UI（滑桿或閾值設定）

### Pixiv 瀏覽器 Phase 1（Client + Router）

> 依賴：已有 pixivpy3 OAuth refresh_token 機制（settings.py）

#### 服務層
- [ ] 新建 `services/pixiv_client.py` — async context manager（仿 EhClient）
  - pixivpy3 同步 → `asyncio.to_thread()` 包裝
  - Token 管理：Redis 快取 access_token（TTL 3500s）+ Redis lock 防競爭刷新
  - httpx client（`Referer: https://www.pixiv.net/`）用於圖片下載
  - 方法：search_illust / illust_detail / user_detail / user_illusts / user_bookmarks / illust_follow / user_following / download_image

#### Router
- [ ] 新建 `routers/pixiv.py` — 所有端點 `Depends(require_auth)`
  - `GET /search` — 搜尋插畫（word, sort, search_target, duration, offset）
  - `GET /illust/{id}` — 插畫詳情
  - `GET /user/{id}` — 使用者資訊 + 近期作品
  - `GET /user/{id}/illusts` — 分頁使用者作品
  - `GET /user/{id}/bookmarks` — 使用者公開收藏
  - `GET /following/feed` — 已追蹤作者的新作品
  - `GET /image-proxy` — 代理 pximg.net 圖片（domain 白名單 + Redis 24h 快取）
- [ ] `main.py` 註冊 `/api/pixiv` router

#### 基礎設施
- [ ] `services/cache.py` 新增 Pixiv 快取 helpers（search 5min / illust 1h / user 30min / image 24h）
- [ ] `core/config.py` 新增 `pixiv_max_concurrency` / `pixiv_image_concurrency`

### i18n 補完
- [ ] 韓文翻譯補齊缺失的 28 keys（ko.ts 511 → 539）
- [ ] 使用者 locale 偏好存入 DB（目前僅 localStorage，換裝置需重選）

### 效能
- [ ] Gallery 列表頁大量資料效能優化（虛擬滾動 / infinite scroll）
- [ ] 縮圖懶載入（Intersection Observer，目前是否已實作待確認）

---

## P2 — 中期功能（有依賴鏈）

> 依賴 P1 完成或需多階段實施。

### Pixiv Phase 2: 作者追蹤（依賴 Phase 1）

#### 資料庫
- [ ] `db/models.py` + `db/init.sql` 新增 `followed_artists` 表
  - 欄位：user_id, source, artist_id, artist_name, artist_avatar, last_checked_at, last_illust_id, auto_download, added_at
  - UNIQUE(user_id, source, artist_id)

#### API 端點
- [ ] `GET /artists/followed` — 列出已追蹤作者
- [ ] `POST /artists/follow` — 追蹤作者
- [ ] `DELETE /artists/follow/{artist_id}` — 取消追蹤
- [ ] `PATCH /artists/follow/{artist_id}` — 切換 auto_download
- [ ] `POST /artists/check-updates` — 手動觸發更新檢查

#### Worker 定時任務
- [ ] `worker.py` 新增 `check_pixiv_artists` cron（每 2 小時）
  - 遍歷 followed_artists → user_illusts → 比對 last_illust_id → 新作品時更新 DB + 可選自動下載
  - 請求間隔 ≥ 2s（Pixiv 限速較嚴）

### Pixiv Phase 3: 原生下載器（依賴 Phase 1）
- [ ] 新建 `services/pixiv_downloader.py`（仿 eh_downloader.py）
  - `download_pixiv_illust()` — 下載單一插畫（含多頁漫畫）
  - `download_pixiv_user_works()` — 下載作者全部作品
  - 輸出 `metadata.json` 相容現有 `import_job`
- [ ] `worker.py` download_job 新增 Pixiv 分支（URL 偵測 → 原生下載器，取代 gallery-dl subprocess）

### Pixiv Phase 4: 前端頁面（依賴 Phase 1-3）

#### Types / API / i18n
- [ ] `types.ts` 新增 PixivIllust / PixivUser / PixivSearchResult 型別
- [ ] `api.ts` 新增 pixiv namespace（search, illust, user, imageProxy, follow）
- [ ] `i18n/en.ts` 新增 `pixiv.*` keys

#### 頁面
- [ ] `/pixiv` 搜尋頁 — 關鍵字搜尋 + 排序/時間篩選 + 結果 grid（仿 `/browse`）
- [ ] `/pixiv/illust/[id]` 插畫詳情 — 大圖、tags、stats、下載按鈕
- [ ] `/pixiv/user/[id]` 作者頁 — 作品 grid、追蹤按鈕
- [ ] `/pixiv/following` 追蹤管理 — 已追蹤作者列表 + 新作品 feed

#### 導航
- [ ] Sidebar + MobileNav 新增 Pixiv 入口

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

### 安全補強
- [ ] 檔案上傳 MIME 驗證（import 時驗證實際檔案類型）

### 後端 i18n
- [ ] 後端 API 錯誤訊息 i18n（目前後端回傳硬編碼中/英文）
- [ ] API 錯誤回應根據 `Accept-Language` header 回傳對應語言
- [ ] Tag 翻譯系統已有 — 確認前端有顯示翻譯後的 tag 名稱

### 前端 i18n 補完
- [ ] 日期/數字格式化根據 locale（`Intl.DateTimeFormat` / `Intl.NumberFormat`）
- [ ] 複數形式支援（1 file vs 2 files）

---

## P3 — 長期 / 按需

> 非核心功能、大型重構、按需啟動。

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

### DevOps
- [ ] 資料庫自動遷移機制（Alembic 或類似工具）
- [ ] 自動化 CI：push 時跑 backend pytest + frontend vitest
- [ ] 集中式日誌（Loki + Grafana 或類似方案）
- [ ] 容器資源限制（`deploy.resources` in docker-compose）
- [ ] Docker image 瘦身：檢查 layer 大小，移除不必要依賴
- [ ] 生產環境 HTTPS 配置指南（Let's Encrypt + Nginx）

### i18n 擴展
- [ ] 簡體中文（zh-CN）翻譯檔
- [ ] 社群貢獻翻譯指南文件

### 測試補強
- [ ] AI tagging 端對端測試（mock ONNX model）
- [ ] CAS 儲存壓力測試（大量重複檔案去重驗證）
- [ ] Import 大量檔案效能測試（1000+ 圖片單次匯入）
- [ ] WebSocket 斷線重連測試
- [ ] Redis 快取命中率監控端點

---

## 已完成（v0.1 歷史記錄）

<details>
<summary>展開已完成項目</summary>

### 功能
- [x] E-Hentai 瀏覽器（搜尋、排行榜、收藏夾、圖片代理）
- [x] 下載引擎（gallery-dl + EH 自有引擎，download→import→thumbnail pipeline）
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
- [x] i18n 四語系（en/zh-TW/ja/ko）
- [x] 下載來源自動偵測（移除手動 source 選擇）
- [x] Stale session 修復

### PWA
- [x] `manifest.json` 加入 `share_target` 宣告（接收 URL text）
- [x] Share Target 落地頁（`/share-target`）：接收分享的 URL
- [x] 落地頁自動呼叫 `_detect_source` → 顯示預覽 → 一鍵下載
- [x] 確認現有 `/api/download/enqueue` 支援從手機端呼叫（CORS/cookie）
- [x] 新增簡化端點 `POST /api/download/quick`（只需 URL，其餘自動）
- [x] 分享成功 toast 通知
- [x] 離線時排隊（SW 快取分享請求，上線後補發）

### DevOps
- [x] Docker 雙網路隔離
- [x] Nginx healthcheck
- [x] Multi-stage Dockerfile
- [x] backup/restore 腳本
- [x] Worker max_jobs + LOG_LEVEL 環境變數
- [x] .dockerignore

### 測試
- [x] Backend 221 tests
- [x] Frontend 242 tests

</details>
