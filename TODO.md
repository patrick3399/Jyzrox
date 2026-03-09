# Jyzrox TODO

> 最後更新：2026-03-09

---

## v0.1 收尾（已完成功能的補完）

### i18n 補完
- [ ] 韓文翻譯補齊缺失的 28 keys（ko.ts 511 → 539）
- [ ] 後端 API 錯誤訊息 i18n（目前後端回傳硬編碼中/英文）
- [ ] 使用者 locale 偏好存入 DB（目前僅 localStorage，換裝置需重選）

### Service Worker 強化
- [ ] 自動版本管理 — build 時注入 hash 或時間戳到 `CACHE_NAME`
- [ ] SW 更新提示 UI（偵測到新版本時提示使用者重整）

### AI Tagging 上線準備
- [ ] 測試 `TAG_MODEL_ENABLED=true` 完整流程（模型下載→推理→DB 寫入）
- [ ] 前端：Gallery detail 頁顯示 AI 標籤（含信心度）
- [ ] 前端：「重新標記」按鈕整合到 Gallery detail
- [ ] 標籤信心度篩選 UI（滑桿或閾值設定）

---

## Pixiv 瀏覽器

### 後端 API
- [ ] `routers/pixiv.py` — Pixiv 搜尋端點（關鍵字、排序、篩選）
- [ ] Pixiv 插畫詳情端點（metadata、tags、作者資訊）
- [ ] Pixiv 圖片代理（同 EH proxy 架構，semaphore + cache）
- [ ] Pixiv 使用者/作者頁端點（作品列表、分頁）
- [ ] Pixiv 排行榜端點（每日/每週/每月）
- [ ] Pixiv 收藏端點（取得/新增/移除收藏）
- [ ] `main.py` 註冊 `/api/pixiv` router

### 前端頁面
- [ ] `/pixiv` 搜尋頁 — 關鍵字搜尋 + 篩選（類似 `/browse`）
- [ ] Pixiv 插畫詳情 modal/頁面（大圖、tags、作者連結）
- [ ] Pixiv 使用者頁面（作品 grid）
- [ ] Pixiv 排行榜頁面
- [ ] Pixiv 收藏管理 UI
- [ ] 側邊欄新增 Pixiv 入口

### 下載整合
- [ ] Pixiv URL auto-detect 已有（`_detect_source`），確認 gallery-dl 下載流程正常
- [ ] Pixiv 多圖作品（漫畫/系列）下載支援驗證

---

## 大量下載

### 後端
- [ ] 批次下載 API：接受標籤/作者/搜尋條件，列舉所有符合的 gallery
- [ ] 批次 enqueue 機制（避免一次灌入數千 job 壓垮 worker）
- [ ] 批次任務進度追蹤（Redis：總數/已完成/失敗）
- [ ] E-Hentai 標籤全下載（爬取搜尋結果所有頁 → 逐一 enqueue）
- [ ] Pixiv 作者全作品下載（取得作品列表 → 逐一 enqueue）
- [ ] 下載速率限制設定（避免被封 IP）

### 前端
- [ ] 批次下載 UI 入口（從搜尋結果頁觸發）
- [ ] 批次任務儀表板（總進度、成功/失敗統計）
- [ ] 批次下載確認 dialog（預覽數量、預估大小）

---

## 手機分享→PWA 下載

### PWA 配置
- [x] `manifest.json` 加入 `share_target` 宣告（接收 URL text）
- [x] Share Target 落地頁（`/share-target`）：接收分享的 URL
- [x] 落地頁自動呼叫 `_detect_source` → 顯示預覽 → 一鍵下載

### 後端
- [x] 確認現有 `/api/download/enqueue` 支援從手機端呼叫（CORS/cookie）
- [x] 新增簡化端點 `POST /api/download/quick`（只需 URL，其餘自動）

### UX
- [x] 分享成功 toast 通知
- [x] 離線時排隊（SW 快取分享請求，上線後補發）

---

## 多人權限管理

### 資料庫
- [ ] `users` 表新增 `role` 欄位（`admin` / `member` / `viewer`）
- [ ] 遷移腳本：現有使用者預設 `admin`
- [ ] `gallery_permissions` 表（gallery_id, user_id, permission_level）

### 後端
- [ ] `core/auth.py` — `require_role(role)` dependency（檢查角色權限）
- [ ] 管理端點：列出使用者、修改角色、停用帳號
- [ ] Gallery 權限控制：私有/公開/指定使用者可見
- [ ] 下載/匯入操作的權限檢查（member 以上）
- [ ] 設定頁（credentials、system）限 admin

### 前端
- [ ] 使用者管理頁（`/admin/users`）：列表、角色切換、停用
- [ ] Gallery 分享 UI：設定可見性、邀請使用者
- [ ] 角色不足時的 403 提示頁面
- [ ] 側邊欄根據角色隱藏管理入口

---

## Plugin 系統

### 核心架構
- [ ] Plugin 介面定義（Python ABC）：`on_download`, `on_import`, `on_tag` hooks
- [ ] Plugin 載入器：掃描 `plugins/` 目錄，動態載入
- [ ] Plugin 設定 schema（每個 plugin 可宣告自己的設定欄位）
- [ ] Plugin 生命週期管理（enable/disable/configure）

### 內建 Plugin（驗證架構）
- [ ] 通知 Plugin：下載完成時發送 Telegram/Discord webhook
- [ ] 自訂 metadata Plugin：從檔名/路徑萃取額外 tags

### 管理介面
- [ ] `/settings/plugins` 頁面：列出已安裝 Plugin
- [ ] Plugin 啟用/停用開關
- [ ] Plugin 設定表單（動態生成）

---

## 多國語言（i18n 擴展）

### 後端 i18n
- [ ] API 錯誤回應根據 `Accept-Language` header 回傳對應語言
- [ ] 使用者 locale 欄位存入 DB（`users.locale`）
- [ ] Tag 翻譯系統已有 — 確認前端有顯示翻譯後的 tag 名稱

### 前端補完
- [ ] 韓文缺失 keys 補齊
- [ ] 日期/數字格式化根據 locale（`Intl.DateTimeFormat` / `Intl.NumberFormat`）
- [ ] 複數形式支援（1 file vs 2 files）

### 新語系擴展（按需）
- [ ] 簡體中文（zh-CN）翻譯檔
- [ ] 社群貢獻翻譯指南文件

---

## 品質與穩定性

### 測試
- [ ] AI tagging 端對端測試（mock ONNX model）
- [ ] CAS 儲存壓力測試（大量重複檔案去重驗證）
- [ ] Import 大量檔案效能測試（1000+ 圖片單次匯入）
- [ ] WebSocket 斷線重連測試

### 效能
- [ ] Gallery 列表頁大量資料效能優化（虛擬滾動 / infinite scroll）
- [ ] 縮圖懶載入（Intersection Observer，目前是否已實作待確認）
- [ ] Redis 快取命中率監控端點

### 安全
- [ ] Rate limiting 全端點覆蓋（目前僅 external API 有）
- [ ] CSRF protection（目前 cookie-based auth 無 CSRF token）
- [ ] 檔案上傳 MIME 驗證（import 時驗證實際檔案類型）

---

## DevOps

- [ ] 集中式日誌（Loki + Grafana 或類似方案）
- [ ] 容器資源限制（`deploy.resources` in docker-compose）
- [ ] 自動化 CI：push 時跑 backend pytest + frontend vitest
- [ ] Docker image 瘦身：檢查 layer 大小，移除不必要依賴
- [ ] 資料庫自動遷移機制（Alembic 或類似工具）
- [ ] 生產環境 HTTPS 配置指南（Let's Encrypt + Nginx）

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
