# Jyzrox TODO

> 最後更新：2026-03-11

---

## P1 — 短期高價值

> 獨立功能，少依賴，能快速上線。

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

- [ ] 安裝 SAQ，建立基礎 worker 設定（`worker/saq_worker.py`）
- [ ] 遷移 job functions（`download_job`, `import_job`, `tag_job`, `subscription_check`）
- [ ] 遷移 cron scheduling（subscription 定時檢查）
- [ ] 替換 `arq.create_pool` → SAQ queue（`core/redis_client.py`, enqueue 呼叫點）
- [ ] 更新 Docker entrypoint（`saq worker.saq_worker:settings`）
- [ ] 移除 arq 依賴 + `core/compat.py` monkey-patch
- [ ] 驗證：Python 3.14 環境下完整 worker pipeline 正常運行
- [ ] 可選：啟用 SAQ Web UI dashboard

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
