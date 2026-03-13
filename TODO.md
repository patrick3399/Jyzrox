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
- [ ] 單一 Gallery 下載前預覽：貼入 URL 後顯示頁數、estimated size、tag 清單（EH gdata API），讓用戶決定是否下載

#### 獨立項目
- [x] ~~下載速率限制設定：per-site concurrency / delay_ms~~ → 移至「統一限速控制」完成
- [x] ~~時段排程解鎖~~ → 移至「統一限速控制」完成
- [ ] Hentai@Home 支援：EH plugin 偵測 H@H 可用時自動解鎖限速（或手動覆蓋）

> ✅ 已套用：`enqueue` 端點已加 `require_role("member")`，job 列表依角色篩選

---

### ~~下載失敗自動重試排程~~ ✅ Done

> 自動重試 failed/partial job + 偵測損壞圖片 + 持久化缺頁資訊。

- [x] `download_jobs` 新增 `retry_count`、`max_retries`、`next_retry_at` 欄位
- [x] 新增 "partial" 狀態：下載部分完成（有缺頁）仍觸發 import，缺頁記錄在 `progress.failed_pages`
- [x] 圖片完整性驗證：magic bytes 檢查，損壞檔案自動刪除並標記為 partial
- [x] Cron job `retry_failed_downloads_job`：每 15 分鐘掃描 failed/partial jobs，指數退避重試（base_delay × 2^retry_count，上限 24h）
- [x] `FOR UPDATE SKIP LOCKED` + `LIMIT 10` 防止競爭和批量湧入
- [x] Redis 設定：`retry_enabled`、`retry_max_retries`、`retry_base_delay_minutes`
- [x] 手動重試端點：`POST /api/download/jobs/{id}/retry`（member 角色）
- [x] 前端：partial amber badge、retry 按鈕、failed pages 計數、permanently failed 提示
- [x] i18n 五語系支援
- [x] 測試：16 backend unit tests + 7 router tests + 2 frontend hook tests

---

### 評分傳播

> **現狀**：`user_ratings` 已有 5 星評分，但評分是孤立的。
>
> **目標**：利用已有評分資料，為新 gallery 提供建議評分，並作為搜尋排序依據。

- [ ] `GET /api/library/galleries/{id}/suggested-rating`：根據同 artist / 相似 tag 組合的歷史評分計算建議值
- [ ] Gallery detail 頁：新 gallery 顯示建議評分（淡色星星），用戶可一鍵採用或自行評分
- [ ] Library 搜尋新增 `predicted_rating` 排序選項（基於 tag 組合的加權平均分）

---

### 軟刪除與垃圾桶

> **現狀**：`DELETE /api/library/galleries/{id}` 是硬刪除（CASCADE delete + ref_count decrement + filesystem cleanup），不可逆。對大量收藏的系統，誤刪代價極高。
>
> **目標**：刪除操作改為軟刪除，保留 30 天恢復窗口。

- [ ] `galleries` 表新增 `deleted_at TIMESTAMPTZ`（nullable，Alembic migration）
- [ ] 刪除 API 改為設定 `deleted_at = now()`，不實際移除資料
- [ ] 所有 gallery query 加 `WHERE deleted_at IS NULL` 過濾（或用 SQLAlchemy event/mixin 統一處理）
- [ ] `POST /api/library/galleries/{id}/restore`：恢復軟刪除的 gallery（清除 `deleted_at`）
- [ ] GC cron job：`deleted_at < now() - 30d AND ref_count = 0` 的 blob 才真正清理檔案
- [ ] 前端：`/trash` 頁面（垃圾桶），顯示已刪除 gallery + 剩餘天數 + 恢復/永久刪除按鈕
- [ ] 設定：`trash_retention_days`（default `30`）

---

### 批次 Tag 編輯

> **現狀**：`POST /api/library/galleries/batch` 支援 `favorite/unfavorite/rate/add_to_collection/delete`，但缺少 tag 操作。
>
> **目標**：Library 選取多個 gallery，一次加 tag / 移除 tag。

- [ ] `BatchAction` 新增 `add_tags` / `remove_tags` action（`tags: list[str]` 參數）
- [ ] 後端：批次 upsert / delete `gallery_tags` + 更新 `galleries.tags_array` + tag count
- [ ] 前端：Library 多選模式工具列新增「+Tag」「-Tag」按鈕，彈出 TagInput 元件

---

### 閱讀清單 / 稍後閱讀

> **現狀**：`user_favorites`（語義=喜歡）、`collections`（語義=分類），沒有「我要看這個」的概念。
>
> **目標**：比 Collection 輕量、比 Favorites 不同語義的「稍後閱讀」清單。

- [ ] `reading_list` 表：`(user_id, gallery_id)` PK、`added_at`、`priority SMALLINT`（可選排序）
- [ ] `POST/DELETE /api/library/reading-list/{gallery_id}`：加入 / 移出
- [ ] `GET /api/library/reading-list`：清單端點（支援排序、分頁）
- [ ] Library 搜尋語法新增 `readlater:true` token
- [ ] EH / Pixiv 瀏覽頁「稍後閱讀」按鈕（加入 reading list，不需先下載）
- [ ] 前端：Library filter 新增「稍後閱讀」、Dashboard 顯示待讀數量

---

### RSS 訂閱輸出

> **現狀**：Subscription 系統有增量追蹤資料，但無對外 feed。
>
> **目標**：讓不想裝 PWA 的用戶用任何 RSS reader 追蹤新內容。零成本高價值。

- [ ] `GET /api/subscriptions/{id}/rss`：Atom/RSS feed（最近 N 筆 new works，含封面縮圖 `<enclosure>`）
- [ ] 認證：token query param（`?token=xxx`）或沿用 External API token
- [ ] `GET /api/library/recent/rss`：最近入庫 gallery 的 RSS feed
- [ ] 前端：Subscription detail 頁顯示 RSS URL 複製按鈕

---

### 畫質自動洗版 (Auto-Upgrade Pipeline)

> **現狀**：Subscription 系統追蹤新作品，Dedup 系統有 pHash 比對 + `quality_conflict` heuristic + `suggested_keep` 邏輯。但兩者獨立運作，沒有「發現高畫質版本 → 自動替換」的串接。
>
> **目標**：類似 Radarr 的自動升級——訂閱發現高畫質版本時，自動下載並替換舊版，保留 tag 和閱讀紀錄。

- [ ] `import_job` 完成後觸發畫質比對：新 gallery 的 blob 與同 `(source, source_id)` 或相似 title 的舊 gallery 做 pHash 匹配
- [ ] 替換判定邏輯：新 blob `width * height > 舊 blob * 1.5`（面積增 50% 以上）且 `hamming_dist < threshold`
- [ ] 自動替換流程：更新 `images.blob_sha256` → 新 blob、舊 blob `ref_count--`、保留 `gallery_tags` + `read_progress` + `user_ratings`
- [ ] 替換記錄：`gallery_upgrades` 表（`gallery_id`、`old_sha256`、`new_sha256`、`reason`、`upgraded_at`）
- [ ] 設定：`auto_upgrade_enabled`（default `false`）、`auto_upgrade_min_area_ratio`（default `1.5`）
- [ ] 前端：Gallery detail 頁顯示升級歷史、Settings 開關

---

## P2 — 中期功能（有依賴鏈）

> 需多階段實施或依賴較多。

### 動態影像交付 (Dynamic Image Delivery)

> **現狀**：Worker 預生成 160/360/720px WebP 靜態縮圖（`/media/thumbs/`），Nginx 直接 serve。格式固定為 WebP，尺寸只有三檔。
>
> **目標**：引入動態裁切/轉碼層，支援按需尺寸 + AVIF 格式，省硬碟空間 + 減少行動端頻寬。

#### 方案選擇
- **imgproxy**（推薦）：Go 寫的獨立微服務，Docker 部署，URL 簽名防濫用，原生支援 AVIF/WebP/JPEG
- **libvips + FastAPI endpoint**：Python binding，不需額外容器，但 CPU 開銷在 API 進程內
- **Nginx image_filter module**：最輕量但功能有限（無 AVIF）

#### 實施
- [ ] 新增 `imgproxy` service（Docker Compose），掛載 `/data/cas/` 為 local source
- [ ] Nginx 新增 `/media/image/{sha256}` location → proxy_pass 到 imgproxy
- [ ] URL 格式：`/media/image/{sha256}?w=400&h=0&format=avif&q=80`（imgproxy signing）
- [ ] 前端 `<img>` 改用 `<picture>` + `srcset`：AVIF 優先、WebP fallback、按 viewport 選尺寸
- [ ] Nginx 快取層：`proxy_cache` 快取已生成的動態圖（避免重複轉碼）
- [ ] 遷移策略：保留現有靜態縮圖作為 fallback，動態層逐步接管
- [ ] 可選：移除 Worker 預生成縮圖步驟，完全改為 on-demand（需評估首次載入延遲）

---

### 全域事件總線 (Event Bus)

> **現狀**：Redis Pub/Sub 已用於 WebSocket 推送（`publish_job_event` → `download:events`），但只涵蓋 download 事件，且只面向內部 WS。P3 的 Webhook/Telegram Plugin 規劃把事件邏輯寫在 Plugin 層。
>
> **目標**：將 Event Bus 從 Plugin 邏輯中抽出為基礎設施層。所有系統事件統一廣播，Plugin/Webhook/WS 都只是 consumer。

#### 核心
- [ ] `core/events.py`：`EventBus` 抽象，基於 Redis Pub/Sub，channel = `events:{type}`
- [ ] 標準事件類型：`gallery.downloaded`, `gallery.deleted`, `gallery.imported`, `tag.added`, `dedup.resolved`, `subscription.checked`, `download.failed`
- [ ] 事件 payload 標準化：`{ event_type, timestamp, actor_user_id, resource_type, resource_id, data }`
- [ ] 所有現有 `publish_job_event` 呼叫遷移到 EventBus

#### Consumer
- [ ] WebSocket handler 改為訂閱 EventBus（取代直接 pubsub）
- [ ] P3 Webhook Plugin 改為 EventBus consumer（不再自己監聽事件）
- [ ] P3 Telegram/Discord Plugin 同上
- [ ] `GET /api/system/events`：最近 N 筆事件查詢（admin，用於 debug）

> 注意：這是 P3 Plugin 系統 + Webhook 的前置基礎設施。先建 Event Bus，Plugin 才能乾淨地掛上去。

---

### OIDC / SSO / LDAP 單一登入

> **現狀**：系統登入完全是自有 username/password → httpOnly cookie session。`OAuthConfig` model 存在但是給來源站 credential 用的（Pixiv OAuth），非系統登入。
>
> **目標**：支援 OAuth2/OIDC + 直接 LDAP bind，覆蓋自架社群兩大主流身份源。

#### 共用基礎
- [ ] `users` 表新增 `external_id TEXT`（OIDC sub / LDAP DN）、`auth_provider`（`local`/`oidc`/`ldap`）
- [ ] User auto-provisioning：首次外部登入自動建立 `users` 記錄（預設角色可設定）
- [ ] 設定：`external_auth_default_role`（default `viewer`）、`external_auth_auto_provision`（開關）

#### Phase 1：OIDC
- [ ] 設定欄位：`oidc_enabled`、`oidc_client_id`、`oidc_client_secret`、`oidc_issuer_url`、`oidc_redirect_uri`
- [ ] `GET /api/auth/oidc/login`：redirect 到 OIDC provider authorize endpoint
- [ ] `GET /api/auth/oidc/callback`：處理 callback，驗證 id_token，auto-provision 或 link 到既有用戶
- [ ] OIDC group claim → Jyzrox role 映射（`oidc_role_mapping` JSON 設定）

#### Phase 2：LDAP
- [ ] 依賴：`ldap3` 套件
- [ ] 設定欄位：`ldap_enabled`、`ldap_url`（`ldap://openldap:389`）、`ldap_bind_dn`、`ldap_bind_password`、`ldap_base_dn`、`ldap_user_filter`（default `(uid={username})`）、`ldap_tls`（開關）
- [ ] `POST /api/auth/login` 擴展：當 `ldap_enabled=true` 時，先嘗試 LDAP bind 驗證，失敗再 fallback 到 local password
- [ ] LDAP group → Jyzrox role 映射：`ldap_role_mapping` JSON（`memberOf` attribute → `admin`/`member`/`viewer`）
- [ ] LDAP → 群組同步（可選）：LDAP group 自動對應 P2 的 `groups` 表

#### 前端
- [ ] `/login` 頁面：根據啟用狀態顯示「Login with SSO」按鈕（OIDC）和/或 LDAP 提示文字
- [ ] `/settings` 頁面：OIDC + LDAP 設定區塊（admin only），含 LDAP 連線測試按鈕
- [ ] User profile 頁：顯示認證來源（local / OIDC / LDAP）

---

### 群組與資料夾級 ACL 權限

> **現狀**：RBAC 三級角色（admin/member/viewer）是全域的。`gallery_permissions` 表已規劃（P2 Gallery 分享）但是 per-gallery per-user，沒有群組概念，也沒有資料夾（library path）級的權限。
>
> **目標**：支援「群組」作為權限單位，可按 library path / collection 設定 ACL。

#### Phase 1：群組基礎
- [ ] `groups` 表：`id`、`name`、`description`、`created_by`、`created_at`
- [ ] `group_members` 表：`(group_id, user_id)` PK、`role`（`admin`/`member`）、`joined_at`
- [ ] `GET/POST/PATCH/DELETE /api/groups`：群組 CRUD（admin only）
- [ ] `POST/DELETE /api/groups/{id}/members`：成員管理
- [ ] 前端：`/admin/groups` 管理頁面

#### Phase 2：資料夾級 ACL
- [ ] `library_path_acl` 表：`(library_path_id, group_id)` PK、`permission`（`read`/`write`/`none`）
- [ ] `gallery_access_filter()` 擴展：加入 library path ACL 過濾（用戶所屬群組 → 可見 library path → 可見 gallery）
- [ ] `gallery_permissions` 表支援 `group_id`（除了現有的 per-user）
- [ ] 前端：Library Path 設定頁新增群組權限設定

---

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
- [ ] 公開分享模式：允許用戶以唯讀模式對外公開 library（自架 booru），配合 OPDS 讓任何支援的 reader 可訂閱

---

### Gallery 合併

> **現狀**：Dedup 系統在 blob 層級運作（pHash 比對），但沒有 gallery 層級的重複偵測與合併功能。
>
> **目標**：當兩個 gallery 有大量重複 blob 時，提供合併機制（選擇保留哪個、合併 metadata/tag）。

- [ ] Gallery 重複偵測：在 `blob_relationships` 基礎上聚合——若兩個 gallery 間重複 blob 數量超過閾值，標記為疑似重複
- [ ] `GET /api/dedup/gallery-pairs`：gallery 層級的重複列表（含重複率、共用 blob 數量）
- [ ] `POST /api/dedup/gallery-merge`：合併操作（指定保留 gallery，合併 tag/metadata，重新指向 images）
- [ ] 前端：Dedup 頁面新增「Gallery 重複」tab，顯示 gallery pair 並排比較、一鍵合併

---

### Gallery 版本歷史

> **現狀**：EH gallery 以 `(source, source_id)` 為 UNIQUE key。同一內容 expunge 後重新上傳會有不同 gid，系統視為全新 gallery。
>
> **目標**：偵測「這可能是某個 gallery 的新版本」，讓用戶決定替換或保留兩者。

- [ ] 版本偵測邏輯：同 artist + title 高相似度（`pg_trgm`）+ 頁數接近 → 標記為疑似新版本
- [ ] `gallery_versions` 表：`(gallery_id, previous_gallery_id)`，記錄版本鏈
- [ ] Import pipeline：`import_job` 完成後觸發版本比對，發現疑似新版本時寫入 `gallery_versions` + 推送通知
- [ ] `GET /api/library/galleries/{id}/versions`：回傳版本鏈（含每個版本的 diff 摘要：新增/移除頁數、tag 差異）
- [ ] 前端：Gallery detail 頁顯示「此 gallery 可能是 XXX 的新版本」提示，提供「替換舊版」/「保留兩者」選項

---

### 匯入衝突解決 UI

> **現狀**：`importer.py` 對同 `(source, source_id)` 使用 `on_conflict_do_update`，靜默覆蓋 `title`、`tags_array`、`pages`。用戶手動編輯的 tag 可能被覆蓋，且無任何通知。
>
> **目標**：偵測衝突時記錄差異，讓用戶決定跳過、合併、覆蓋。

- [ ] `import_conflicts` 表：`id`、`gallery_id`、`source`、`source_id`、`old_data JSONB`、`new_data JSONB`、`status`（pending/resolved）、`resolution`（skip/merge/overwrite）、`created_at`
- [ ] `import_job` 修改：衝突時不直接 `on_conflict_do_update`，改為寫入 `import_conflicts` 並標記 `status=pending`
- [ ] `GET /api/import/conflicts`：衝突列表（含 diff 預覽）
- [ ] `POST /api/import/conflicts/{id}/resolve`：`action=skip|merge|overwrite`
  - `merge`：保留用戶手動 tag + 合併 metadata 新增欄位
  - `overwrite`：完整覆蓋
  - `skip`：不更新
- [ ] 前端：Import Center 新增「衝突」tab，逐筆顯示 old vs new diff + 操作按鈕
- [ ] 設定：`import_conflict_mode`（`auto_overwrite`/`auto_merge`/`manual`），default `manual`

---

### 閱讀統計

> **現狀**：`read_progress` 只記錄最後一頁（書籤），無法統計閱讀行為。
>
> **目標**：基於閱讀事件，提供每週頁數、常讀 tag 分布、未讀完 gallery 等統計。

#### 後端
- [ ] `read_events` 表：`user_id`、`gallery_id`、`pages_read`、`duration_seconds`、`started_at`、`ended_at`
- [ ] Reader 關閉/切換 gallery 時寫入一筆 event（前端 → `POST /api/library/read-events`）
- [ ] `GET /api/library/stats`：每週/每月已讀頁數、常讀 tag TOP N、未讀完 gallery 列表
- [ ] 自動清理：保留最近 N 天（可設定）

#### 前端
- [ ] Dashboard widget 或 `/stats` 頁面：閱讀趨勢圖表、常讀 tag 分布、「繼續閱讀」列表

#### 進階：閱讀熱力圖與年度回顧 (Wrapped)
> 依賴 `read_events` 資料。GitHub 風格的閱讀統計 + 年底回顧。
- [ ] `GET /api/library/stats/heatmap`：每日閱讀頁數（365 天），用於渲染 GitHub contribution 風格的熱力圖
- [ ] `GET /api/library/stats/wrapped?year=2026`：年度回顧摘要（總 gallery 數、總頁數、最愛畫師 TOP 5、最常讀 tag、閱讀高峰時段）
- [ ] 前端：`/stats` 頁面嵌入 SVG 熱力圖元件 + 年度回顧卡片（可分享截圖）

---

### Tag 健康度報告

> **現狀**：`tags` 有 count、aliases、implications，但沒有品質監控。
>
> **目標**：自動偵測問題 tag（孤立、疑似拼錯、循環 implication），產出需人工確認的清單。

- [ ] `GET /api/tags/health`：回傳問題 tag 報告
  - 孤立 tag：`count=1` 且無 alias 指向
  - 疑似重複：`pg_trgm similarity > 0.6` 但不是已知 alias
  - 循環 implication：recursive CTE 偵測
- [ ] 前端：Tag 管理頁新增「Health」tab，顯示問題清單 + 一鍵建立 alias / 刪除 / 忽略

---

### 自動 Tag 清理建議

> **現狀**：`gallery_tags.source` 區分 `metadata` 和 `ai`，但 WD14 tag 與 metadata tag 的差異未被比對。
>
> **目標**：tag_job 完成後，若 AI tag 與 metadata tag 差距大，標記異常讓用戶檢查。

- [ ] `tag_job` 結尾新增差異比對：AI 高信心度 tag 不在 metadata 中 / metadata tag 被 AI 完全否定
- [ ] `tag_anomalies` 表（或 Redis key）：`gallery_id`、`type`（`missing_from_metadata`/`ai_disagrees`）、`tag`、`ai_confidence`
- [ ] `GET /api/tags/anomalies`：異常列表（可篩選 gallery / type）
- [ ] 前端：Gallery detail AI tag 區塊標示異常 tag（⚠️ icon），Tag 管理頁新增「Anomalies」tab

---

### SauceNAO Metadata 整合

> **現狀**：Gallery metadata 來自下載來源（EH gdata、Pixiv API、gallery-dl）。對無 metadata 的本地匯入或 booru 圖片，缺乏反向溯源能力。
>
> **目標**：利用 SauceNAO API 反查圖片來源，補充 metadata（artist、source URL、booru tag）。

- [ ] `services/saucenao.py`：SauceNAO API client（`/search/json`，rate limit 6r/30s free tier）
- [ ] 設定：`saucenao_api_key`（可選，free tier 有限制）
- [ ] `tag_job` 或獨立 `saucenao_job`：對無 `source` 的 gallery 取封面圖查 SauceNAO
- [ ] 結果處理：
  - 找到 Pixiv/EH 來源 → 補填 `galleries.source` + `source_id`，觸發 metadata 更新
  - 找到 booru 來源 → 拉取 booru tag 合併到 `gallery_tags`
  - 信心度低（`similarity < 80%`）→ 標記為建議，不自動套用
- [ ] Gallery detail 頁：「查找來源」按鈕（手動觸發 SauceNAO 查詢）
- [ ] 批次操作：對所有 `source IS NULL` 的 gallery 批次查詢

---

### Kohya 匯出改善

> **現狀**：`GET /api/export/kohya/{gallery_id}` 已實作基礎功能（CAS 圖片 + tag .txt 打包 ZIP）。但缺少常見的 Kohya 訓練需求。
>
> **目標**：提升 Kohya 匯出的實用性。

- [ ] 匯出選項：`trigger_word`（每個 .txt 檔開頭加入觸發詞）
- [ ] Tag 格式化選項：namespace 剝離（`general:cat` → `cat`）、排除特定 namespace（如 `meta:`）
- [ ] 圖片處理選項：縮放到指定解析度（`512x512` / `768x768`）、bucket 分桶
- [ ] 批次匯出：選擇多個 gallery 合併匯出為一個 dataset
- [ ] 前端：Export 頁面新增選項表單（trigger word、tag format、resolution）

---

### Browser Extension (Web Clipper)

> **現狀**：PWA Share Target + `POST /api/download/quick` 支援手機分享 URL 下載。Mihon Extension 代碼已存在（`mihon-extension/`）。但沒有桌面瀏覽器的擴充功能，且 Share Target 無法帶目標站的 cookies 繞反爬。
>
> **目標**：Chrome/Edge 擴充功能，右鍵「Send to Jyzrox」。由用戶瀏覽器發送請求，可帶目標站 session cookies，繞過伺服器端反爬。

- [ ] `extension/` 目錄：Manifest V3 Chrome Extension
- [ ] Context menu：右鍵圖片 / 頁面 → 「Send to Jyzrox」
- [ ] 設定頁：Jyzrox instance URL + API token（External API）
- [ ] 發送邏輯：解析當前頁面 DOM 抓圖片 URL + cookies → `POST /api/download/quick`（或新的 `/api/download/external-enqueue`）
- [ ] 後端：新增 `POST /api/download/external-enqueue` 端點，接受帶 cookies 的下載請求（External API token auth）
- [ ] Batch mode：一次收集頁面上所有圖片 URL，批次送出
- [ ] 可選：Firefox 相容（WebExtension API 大致相同）

---

### 動態縮圖與 Ugoira 預覽 (Animated Previews)

> **現狀**：影片頁面有 `VideoPlayer.tsx` 支援 mp4/webm 播放。`thumbnail_job` 會 ffprobe 取首幀。Pixiv 前端知道 ugoira 類型。但 Gallery Grid 沒有 hover 動態預覽。
>
> **目標**：滑鼠 hover Gallery Card 時自動播放前幾秒精華片段。

- [ ] Worker `thumbnail_job` 擴展：影片/GIF/Ugoira 額外生成 3 秒預覽 WebM（`/data/thumbs/{xx}/{sha256}/preview.webm`）
- [ ] Ugoira 支援：Pixiv downloader 下載 ugoira zip → 解壓 frames → ffmpeg 合成 WebM（帶 frame delay）
- [ ] `blobs` 表新增 `has_preview BOOLEAN DEFAULT false`
- [ ] 前端 `GalleryCard`：hover 時載入 `preview.webm`，`<video autoplay muted loop>` 疊加在縮圖上
- [ ] 效能：`IntersectionObserver` 控制只有可見 card 才 preload preview
- [ ] `JustifiedGrid` / `VirtualGrid`：Image Browser 也支援 hover 預覽

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
- [ ] Telegram Bot Plugin：雙向整合（通知 + 接收 URL 下載）
  - 通知：下載完成/失敗、訂閱更新、系統告警 → 發送 Telegram 訊息
  - 接收：用戶傳 URL 給 Bot → 觸發 `download_job` enqueue
  - 設定：`bot_token`、`chat_id`、通知類型開關
  - 依賴 Plugin hook 架構（`on_download_complete`, `on_download_failed` 等）
- [ ] Discord Webhook Plugin：下載完成/失敗通知（webhook URL 設定）
- [ ] Webhook 通用 Plugin：事件（download/subscribe/dedup/import）→ HTTP POST 到用戶自訂 URL
  - 比 Telegram/Discord 更通用，可接 n8n、Home Assistant、自訂 script
  - 設定：`webhook_url`、`secret`（HMAC 簽名）、事件類型勾選
  - payload 格式：`{ event, timestamp, data }` JSON
- [ ] Danbooru 原生 BrowsePlugin：搜尋 / gallery 詳情 / 圖片代理 / tag 補全
  - gallery-dl fallback 已支援 danbooru 下載（domain mapping + SiteInfo 已有）
  - 缺少的是 Browse UI：`/api/danbooru` 搜尋端點 + 前端 `/danbooru` 頁面
  - Danbooru API 是公開 REST，不需 credential（optional API key for rate limit）
  - 同時考慮 Gelbooru / Yandere 等 booru 系的通用 BrowsePlugin（API 格式近似）
- [ ] 自訂 metadata Plugin：從檔名/路徑萃取額外 tags

#### 管理介面
- [ ] `/settings/plugins` 頁面：列出已安裝 Plugin
- [ ] Plugin 啟用/停用開關
- [ ] Plugin 設定表單（動態生成）

---

### 本地 AI 推薦引擎

> **現狀**：已有 WD14 tag、pHash、user_ratings、read_progress，但無推薦邏輯。
>
> **目標**：利用現有資料做「你可能會喜歡」的 gallery 推薦，完全本地運算。
>
> **待評估**：先參考 [Jellyfin 相似影片推薦代碼](https://github.com/jellyfin/jellyfin)（`SimilarItems` 相關模組）或其他輕量推薦系統的實作方式，再決定技術路線。

#### Phase 1：相似 Gallery 推薦（純 SQL，無 ML）
> 不需要機器學習，利用現有 tag / artist / pHash 資料即可。
- [ ] `GET /api/library/galleries/{id}/similar`：tag 向量相似度（`tags_array` 交集/聯集比）+ 同 artist + 頁數接近 → 加權排序
- [ ] Gallery detail 頁：「類似作品」區塊（橫向捲動卡片列表）
- [ ] 可選：結合 `blob_relationships` pHash 資料加權

#### Phase 2：個人化推薦（需評估）
- **Tag-based similarity**：gallery tag 向量 vs 用戶偏好 tag 向量（TF-IDF / cosine similarity）
- **協同過濾**：user-item matrix（ratings + read history），輕量 SVD / ALS
- **Embedding-based**（依賴 pgvector P3）：WD14/CLIP embedding 做語意推薦

#### 待確認後規劃
- [ ] 評估 Jellyfin 參考代碼，確定 Phase 2 技術路線
- [ ] `GET /api/library/recommendations`：個人化推薦端點（per-user）
- [ ] 前端 Dashboard widget 或 Library 排序選項「推薦」

---

### Kavita / Komga 相容 API

> **現狀**：External API (`/api/external/v1`) 提供基礎的 galleries/images/tags 端點，但非 Kavita/Komga 格式。
>
> **目標**：加一個相容層，讓所有支援 Kavita/Komga 的 client（iOS/Android 各種漫畫 app）直接連到 Jyzrox。比寫新 extension 更省事。

- [ ] 評估 Kavita v5 API schema（`/api/series`, `/api/chapter`, `/api/reader`）與 Komga API（`/api/v1/series`, `/api/v1/books`）
- [ ] 決定相容哪一個（或兩者）：Kavita 用戶更多，Komga API 更簡潔
- [ ] `/api/compat/kavita/` 或 `/api/compat/komga/`：adapter 層將 Jyzrox gallery/image 映射為對應格式
- [ ] 認證適配：OPDS Basic Auth / API token → Kavita/Komga 認證格式

---

### 下載速度歷史

> **現狀**：`download_jobs.progress` JSONB 有當前速度，但無歷史紀錄。限速設定缺乏數據依據。
>
> **目標**：記錄 per-source 下載速度歷史，為限速設定提供參考。

- [ ] `download_speed_log` 表（或 Redis time series）：`source`、`avg_speed_bps`、`peak_speed_bps`、`sample_count`、`hour_bucket TIMESTAMPTZ`
- [ ] Worker `download_job` 完成時寫入一筆：計算本次 job 的平均速度
- [ ] `GET /api/download/speed-history`：per-source 每小時/每日平均速度（圖表用）
- [ ] 前端：Settings 限速分區新增速度歷史圖表（「EH 在此時段平均 X MB/s」）
- [ ] 自動清理：保留 30 天

---

### Manga OCR 與對白全文檢索

> **現狀**：Gallery 搜尋只靠 tag（GIN array）+ title fuzzy（pg_trgm）。無法搜尋漫畫內的對白文字。
>
> **目標**：OCR 提取氣泡框文字，存入 PostgreSQL FTS，支援「輸入台詞 → 定位到具體頁數」。

#### 後端
- [ ] `ocr` 微服務（獨立容器，`--profile ocr`）：`manga-ocr` 模型（日文）+ `PaddleOCR`（中文 fallback）
  - `POST /ocr/extract`：接受圖片，回傳 `[{ text, bbox, confidence }]`
- [ ] `image_texts` 表：`image_id` FK、`text TEXT`、`bbox JSONB`、`language`、`tsvector` 欄位
- [ ] `ocr_job`：Worker job，import 完成後對每頁圖片呼叫 OCR 微服務，結果寫入 `image_texts`
- [ ] GIN index on `tsvector` 欄位，支援 `ts_query` 全文檢索
- [ ] `GET /api/library/search/dialogue?q=...`：對白搜尋端點，回傳 `{ gallery_id, image_id, page_num, snippet, highlight }`
- [ ] 設定：`ocr_enabled`（default `false`）、`ocr_url`、`ocr_languages`

#### 前端
- [ ] Library 搜尋模式切換：「Tag 搜尋」/「對白搜尋」
- [ ] 搜尋結果：顯示匹配頁面縮圖 + 高亮文字片段 + 一鍵跳轉到 Reader 指定頁

---

### 即時漫畫翻譯 (On-the-fly Translation)

> **現狀**：Tag 有翻譯（`tag_translations`），但漫畫內容本身無翻譯功能。Reader 只顯示原圖。
>
> **目標**：Reader 中按下「翻譯」，動態將翻譯文字疊加在氣泡框上。

> **依賴**：Manga OCR（P3）提供文字位置 + 內容。

- [ ] 翻譯微服務（獨立容器，`--profile translate`）：整合 Sugoi Toolkit / Manga Image Translator API / LibreTranslate
  - `POST /translate`：接受 `{ texts[], source_lang, target_lang }`，回傳翻譯結果
- [ ] `image_translations` 表：`image_id`、`source_lang`、`target_lang`、`translations JSONB`（`[{ original, translated, bbox }]`）
- [ ] 後端：`GET /api/library/images/{id}/translation?lang=en` — 回傳或觸發翻譯
- [ ] 前端 Reader：翻譯 overlay 層，根據 bbox 座標在原圖上覆蓋翻譯文字（CSS absolute positioning / Canvas）
- [ ] 快取：翻譯結果存 DB，同一頁不重複翻譯
- [ ] 設定：`translation_enabled`、`translation_url`、`translation_default_target`

---

### 零散圖自動成冊 (Auto-Clustering)

> **現狀**：Import pipeline 只處理有目錄結構的資料夾。散圖（數千張無結構檔案）匯入會變成一個巨大 gallery 或需手動分類。pHash 和 CLIP 資料基礎設施存在（Dedup + Tagger）。
>
> **目標**：AI 自動將散圖分群為有邏輯的 gallery（按畫師風格、主題、時間段等）。

> **依賴**：WD14 Tagger（特徵提取）+ 可選 pgvector（embedding 儲存）。

- [ ] `POST /api/import/auto-cluster`：接受一個目錄路徑，啟動分群 job
- [ ] `auto_cluster_job`：Worker job，流程：
  1. 掃描目錄所有圖片
  2. 提取特徵：EXIF 時間戳 + WD14 tag 向量 + 可選 CLIP embedding
  3. 分群演算法：DBSCAN / HDBSCAN（密度聚類，不需預設群數）
  4. 每群自動命名（取 TOP tag 組合或時間範圍）
  5. 產出分群結果預覽（不直接建 gallery）
- [ ] `GET /api/import/auto-cluster/{job_id}/preview`：預覽分群結果（每群的代表圖 + 圖片數 + 建議名稱）
- [ ] `POST /api/import/auto-cluster/{job_id}/confirm`：用戶確認後批次建立 gallery
- [ ] 前端：Import Center 新增「自動成冊」入口，分群預覽 UI（可調整分群、拖曳圖片換群）

---

### 沉浸式音效與 BGM 支援

> **現狀**：Import pipeline 支援圖片 + 影片，不含音檔。Reader 無音訊播放功能。
>
> **目標**：支援關聯音軌到 gallery，Reader 中播放對應 BGM（針對附帶音軌的同人誌或視覺小說拆解包）。

- [ ] Import pipeline 擴展：識別 `.mp3`/`.ogg`/`.flac`/`.wav` 音檔，存入 CAS，建立 `gallery_audio` 關聯
- [ ] `gallery_audio` 表：`gallery_id`、`blob_sha256` FK、`track_name`、`track_order`、`duration_seconds`
- [ ] Nginx `/media/audio/` location：serve 音檔（`auth_request` 保護）
- [ ] Reader：底部音訊播放列（play/pause、進度條、音量），自動按 `track_order` 播放
- [ ] Gallery detail 頁：音軌列表 + 手動關聯/取消關聯 UI

---

### 分散式追蹤 (OpenTelemetry)

> **現狀**：Worker job 之間靠 `job_id` 串聯日誌，但不是結構化的 trace。P2 Log Viewer 和 P3 Loki 都是 log 層面，無法把 FastAPI request → Redis enqueue → ARQ Worker → Tagger HTTP → DB write 整條鏈路串起來。
>
> **目標**：導入 OpenTelemetry，在 Jaeger/Zipkin 看到完整的請求瀑布圖。對異步系統的除錯是降維打擊。

- [ ] 安裝 `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi` + `opentelemetry-instrumentation-sqlalchemy` + `opentelemetry-instrumentation-redis`
- [ ] `core/tracing.py`：OTel 初始化（OTLP exporter），`trace_id` 注入 logging context
- [ ] FastAPI middleware：自動為每個 request 生成 span
- [ ] Worker job：從 Redis message 繼承 `trace_id`，建立 child span（`download_job` → `import_job` → `thumbnail_job`）
- [ ] Tagger HTTP call：propagate trace context header 到 tagger 微服務
- [ ] Docker Compose 新增 `jaeger` service（可選，`--profile observability`）
- [ ] 設定：`otel_enabled`（default `false`）、`otel_endpoint`（Jaeger/OTLP collector URL）
- [ ] 與 P2 Log Viewer 整合：log 條目附帶 `trace_id`，可從 log 跳轉到 trace 視圖

---

### DevOps / 基礎設施

- [ ] 集中式日誌（Loki + Grafana）— P3 重量級方案，與 P2 應用內 Log Viewer 並行不衝突
- [ ] Docker image 瘦身：檢查 layer 大小，移除不必要依賴
- [ ] 生產環境 HTTPS 配置指南（Let's Encrypt + Nginx）
- [ ] SMB/CIFS 文件支援：`docker-compose.yml` 範例加入 SMB volume mount（`type: cifs`），搭配文檔說明如何將 NAS SMB share 掛載為 library path
  - 現狀：`library_base_path=/mnt` 可掛載任意 filesystem，但需用戶自行在 host 層處理 SMB mount
  - 目標：提供 Docker Compose 內建 SMB volume 範例 + 常見 NAS（Synology/QNAP/TrueNAS）設定指南
  - 注意：容器 UID `1042:1042` 需對應 SMB share 的 POSIX 權限

### 測試 / 品質

- [ ] AI tagging 端對端測試（mock ONNX model）
- [ ] CAS 儲存壓力測試（大量重複檔案去重驗證）
- [ ] Import 大量檔案效能測試（1000+ 圖片單次匯入）
- [ ] 社群貢獻翻譯指南文件

---

## P4 — 願景 / 探索

> 依賴鏈極長、架構變動大、或需要社群生態配合。記錄方向，待前置項目成熟後啟動。

### 實例聯邦 (Instance Federation)

> **現狀**：External API (`/api/external/v1`) 提供單向唯讀查詢（galleries/images/tags + token auth）。CAS SHA256 天然支援跨實例去重判斷。但沒有雙向發現、同步、或 peer-to-peer 機制。
>
> **目標**：兩台 Jyzrox 互相「加好友」，透明地搜尋 + 同步對方圖庫。
>
> **前置依賴**：P2 Event Bus（同步事件廣播）、P2 OIDC/SSO（跨實例身份互信）、P2 Gallery 分享（可見性控制）。

#### Phase 1：Peer 互聯
- [ ] `peers` 表：`id`、`name`、`api_url`、`api_token`、`status`（active/pending/disabled）、`last_sync_at`
- [ ] `POST /api/peers`：新增 peer（雙向握手：A 向 B 發邀請，B 確認後交換 API token）
- [ ] `GET /api/external/v1/peer/handshake`：握手端點（驗證 + 交換 metadata）

#### Phase 2：跨實例搜尋
- [ ] Library 搜尋語法新增 `source:peer_name` token
- [ ] 搜尋時透過 peer 的 External API 透明拉取結果，合併到本地搜尋結果
- [ ] 結果標記來源（本地 / peer name），點擊跳轉到對應 gallery

#### Phase 3：P2P 同步
- [ ] 「一鍵同步」：選擇 peer 的 gallery → 比對 CAS SHA256 → 已有的 blob 直接 link（秒抓）→ 缺少的才下載
- [ ] 同步歷史 + 衝突解決（同 source_id 在兩邊都有修改時）
- [ ] 可選：ActivityPub 協議適配（讓 Jyzrox 成為 Fediverse 的一員）

---

### Plugin App Store (沙盒化外掛生態)

> **現狀**：Plugin 系統有 ABC + Protocol 架構、`plugin_registry` singleton、`plugin_config` 表。但全是 Python in-process 載入，無沙盒隔離、無跨語言支援。P3 已規劃 Plugin hook lifecycle + 管理 UI。
>
> **目標**：任何人寫一個符合 JSON I/O 規範的腳本（Go/Rust/JS/Python），上傳即用。Core 保持乾淨，網站改版和反爬由社群外掛處理。
>
> **前置依賴**：P3 Plugin 系統完善（hook lifecycle + 載入器 + 管理 UI）。

#### Phase 1：容器化 Plugin
- [ ] Plugin 規範：定義標準 JSON I/O 介面（stdin/stdout 或 HTTP），包含 `download`、`parse`、`tag`、`browse` 四種 capability
- [ ] Plugin 以獨立 Docker 容器運行（Core 透過 HTTP/gRPC 呼叫），自帶依賴，沙盒隔離
- [ ] Plugin manifest：`plugin.json`（name、version、capabilities、config schema、container image）
- [ ] Core 的 `plugin_registry` 擴展：除了 in-process Python，也支援 external container plugin

#### Phase 2：WASM Plugin Runtime
- [ ] 評估 WASM runtime（Wasmtime / Wasmer）作為輕量沙盒替代 Docker
- [ ] WASM Plugin SDK：定義 host function imports（HTTP fetch、DB query、file read）
- [ ] 安全沙盒：限制 memory、CPU time、network access（capability-based）
- [ ] 效能：WASM 啟動 < 10ms vs Docker container 數秒

#### Phase 3：Plugin Marketplace
- [ ] Plugin registry server（類似 npm registry）：`GET /plugins/search`、`GET /plugins/{id}/versions`
- [ ] Jyzrox 內建 Plugin browser：搜尋、安裝、更新、評分
- [ ] 自動更新：Plugin 版本檢查 + one-click upgrade
- [ ] 安全審核：Plugin 簽名驗證、權限聲明（需要哪些 host function）

---

## 擱置中

> 需要特定環境或硬體才能進行，暫不排入。
> OPDS 後端已完整實作（全端點 + OpenSearch + Basic Auth + PSE page streaming）。Mihon Extension 代碼存在但未驗證。兩者的阻塞點都是實體裝置測試。

- [ ] OPDS 實際 client 測試（Panels iOS / KOReader / Chunky）— 後端已完成，需要實體裝置驗證相容性
- [ ] AI Tagging 測試 `TAG_MODEL_ENABLED=true` 完整流程（模型下載→推理→DB 寫入）— 需要 ONNX runtime + 模型
- [ ] Mihon Extension 編譯 + 實機測試（gallery 列表、搜尋、篩選、閱讀）— 需要 Android 裝置
- [ ] Kohya 匯出實際訓練驗證 — 匯出功能已實作，需實際跑 Kohya 訓練確認 tag 格式 / 檔案結構正確

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

### Image Browser（1bimage）
- [x] `/images` 頁面：justified grid 版面、tag 篩選、cursor 分頁
- [x] `JustifiedGrid.tsx` 組件：等高列排版
- [x] `useImageBrowser.ts` SWR hook
- [x] `GET /api/library/images` 後端端點（`backend/routers/library.py`）
- [x] Thumbhash placeholder 整合於圖片瀏覽器

### Thumbhash Pipeline（1bimage）
- [x] `blobs.thumbhash` 欄位（DB schema）
- [x] `backend/worker/thumbnail.py`：縮圖生成時一併計算 thumbhash
- [x] `backend/worker/thumbhash_backfill.py`：補算現有 blob 的 thumbhash backfill job
- [x] 前端 `thumbHashToDataURL` 工具函式

### Reader 效能優化（1bimage）
- [x] `ThumbnailStrip` 虛擬捲動（virtual scroll，保持約 50 個 DOM 元素而非全部渲染）
- [x] 大型圖庫（>500 頁）windowed image loading
- [x] CSS containment 套用

### Gallery 可見性基礎設施（1bimage）
- [x] `galleries.visibility` 欄位（default `'public'`）
- [x] `galleries.created_by_user_id` 欄位
- [x] `core/gallery_access.py`：`gallery_access_filter()` helper

### 下載失敗自動重試（1bimage）
- [x] `download_jobs` 新增 `retry_count` / `max_retries` / `next_retry_at` 欄位
- [x] "partial" 狀態 + 圖片 magic bytes 驗證 + `progress.failed_pages` 持久化
- [x] `retry_failed_downloads_job` cron（指數退避、SKIP LOCKED、LIMIT 10）
- [x] `POST /api/download/jobs/{id}/retry` 手動重試端點
- [x] 前端 Queue 頁面：partial badge、retry 按鈕、failed pages 顯示
- [x] Redis settings（retry_enabled / max_retries / base_delay）
- [x] i18n 五語系 + 25 tests

</details>
