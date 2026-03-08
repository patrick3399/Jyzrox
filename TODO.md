# Jyzrox TODO

> 最後更新：2026-03-09（深度程式碼審查後產出）

---

## 功能開發

### Phase 6: AI Tagging（未開始）
- [x] WD14 tagger 整合（`worker.py` 中 `tag_job` 目前為 stub）
- [x] `TAG_MODEL_ENABLED=true` 時啟用自動標籤
- [x] 標籤信心度閾值設定
- [x] 批次重新標記已有圖庫

### Import 強化
- [x] Import 任務加入進度追蹤（目前 download 有進度但 import 沒有）
- [x] Import 完成後自動觸發 `thumbnail_job`（目前 import_router 的 BackgroundTask 不走 ARQ pipeline）
- [x] 考慮將 import 流程統一改為 ARQ job（與 download pipeline 一致）

### Saved Searches（桌面版已完成）
- [x] 手機版 Saved Searches UI（目前書籤按鈕 `hidden sm:block`，手機版不可見）

### 搜尋增強
- [x] 感知雜湊（perceptual hash）去重（目前僅 SHA256 完全相同）
- [x] 搜尋語法：`sort:posted_at`、`sort:title` 後端已支援，前端 UI 可增加排序選項

---

## Bug 修復（已於本次 session 修復）

- [x] ~~External API `/download` 缺少 ARQ enqueue~~（`external.py`，2026-03-09 修復）
- [x] ~~Nginx cache 目錄未預建~~ → `nginx/Dockerfile` 加入 `mkdir`（2026-03-09 修復）
- [x] ~~Nginx Dockerfile 缺少 `nginx -t` 語法驗證~~（2026-03-09 修復）
- [x] ~~Backend 缺少 `.dockerignore`~~（2026-03-09 建立）

---

## 測試覆蓋

### Backend（221 tests passing）
- [x] `test_eh.py` — E-Hentai router 測試
- [x] `test_search.py` — 搜尋語法解析 + GIN query 測試
- [x] `test_tag.py` — Tag alias/implication CRUD + cycle detection
- [x] `test_settings.py` — 憑證加解密 + API token CRUD
- [x] `test_import.py` — Import 流程 + 重複檢測
- [x] `test_export.py` — Kohya zip export
- [x] `test_external.py` — External API token 驗證 + rate limiting
- [x] `test_history.py` — Browse history CRUD
- [x] `test_worker.py` — Worker pipeline 單元測試

### Frontend（242 tests passing）
- [x] `useGalleries.test.ts` — Library + EH hooks 測試
- [x] Reader component 測試（模式切換、鍵盤導航、進度儲存）
- [x] Browse page 整合測試（搜尋、分頁、saved searches）
- [x] Library page 整合測試（篩選、cursor pagination）

---

## DevOps 改善

### 高優先
- [x] `data/avatars` 目錄權限修正 — gosu entrypoint 自動建立+chown 所有 data 目錄
- [x] Nginx healthcheck — `/nginx-health` location + docker healthcheck (wget)

### 中優先
- [x] Backend Dockerfile 改為 multi-stage build（builder + runtime stages）
- [x] API healthcheck 改用 `wget`（替代 `python -c urllib`，減少開銷）
- [x] `backup.sh` 讀取 `.env` 取得 DB 憑證（不再硬編碼）
- [x] `restore.sh` 停止服務時加入 nginx（已確認原本就有）
- [x] 自動備份排程 — `scripts/backup-cron.sh` wrapper + crontab/systemd 範例

### 低優先
- [ ] Docker network 分段（DB/Redis 獨立子網，僅 api/worker 可存取）
- [ ] Worker `max_jobs` 可透過環境變數設定（目前硬編碼 8）
- [ ] `LOG_LEVEL` 環境變數支援（目前硬編碼 `INFO`）
- [ ] 集中式日誌（ELK / Loki / Datadog）

---

## 程式碼品質

### Backend
- [ ] Tag cycle detection 使用 `collections.deque` 取代 `list.pop(0)`（`tag.py:256`）
- [ ] System router 快取 pattern 定義統一（避免硬編碼重複）
- [ ] `import_router.py` 使用 ORM 取代 raw SQL（目前混用兩種風格）

### Frontend
- [ ] i18n 完整性 — 部分頁面仍有硬編碼中文字串（`library/[id]/page.tsx`）
- [ ] Service Worker 版本管理機制（cache busting 策略）

---

<!-- ## 文件
- [ ] API 文件（OpenAPI/Swagger 已由 FastAPI 自動產生，但需補充描述）
- [ ] 部署指南（首次安裝步驟、環境需求、外部反向代理設定）
- [ ] `.env.example` 補充更詳細的說明（各欄位用途、安全建議） -->
