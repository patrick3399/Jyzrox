# Jyzrox

> **開發中** — 本專案正在積極開發，功能可能尚未完成或隨時變動。
>
> **警告** — 這個專案是由 Vibe Coding 製作而成，可能有未知的安全風險。使用此程式可能造成您在外部網站的帳號遭到封鎖。

自架式圖庫管理平台，基於 Docker Compose 部署。支援從各來源瀏覽、下載、整理與閱讀圖庫，提供現代化 PWA 介面。

## 功能

- **圖庫瀏覽** — 搜尋與瀏覽 E-Hentai / Pixiv，同步雲端收藏
- **下載引擎** — Plugin 架構原生支援（E-Hentai 與 Pixiv），並以 gallery-dl 作為 25+ 站點的後備，提供即時進度追蹤
- **閱讀器** — 單頁、雙頁、條漫（捲動）三種模式，支援觸控與鍵盤操作
- **本地圖庫** — 標籤篩選、評分、閱讀進度管理
- **標籤系統** — 命名空間式標籤，支援別名、蘊含關係與封鎖標籤
- **訂閱系統** — 追蹤創作者，自動偵測新作品
- **收藏集** — 將圖庫整理至自訂收藏集
- **PWA** — 可安裝、行動裝置友好，本地內容支援離線使用

## 技術棧

| 層級 | 技術 |
|------|------|
| 後端 | FastAPI + SQLAlchemy (asyncpg) + ARQ |
| 前端 | Next.js 15 App Router (PWA) |
| 資料庫 | PostgreSQL 15 + Redis 7 |
| 反向代理 | Nginx |
| 下載引擎 | Plugin system + gallery-dl fallback |

API 文件由程式碼自動產生，隨時保持最新：Swagger UI 位於 `/api/docs`，ReDoc 位於 `/api/redoc`。

## 快速開始

```bash
# 複製並設定
git clone https://github.com/patrick3399/Jyzrox.git
cd Jyzrox
cp .env.example .env  # 編輯你的設定

# 啟動
docker compose up -d

# 瀏覽 http://localhost（首次訪問進入設定頁面）
```

## 開發計畫

- [x] Pixiv 來源整合
- [x] 訂閱系統（追蹤創作者）
- [x] Plugin 架構憑證管理
- [ ] AI 自動標籤（WD14）
- [ ] 重複圖片偵測與管理
- [ ] 多使用者支援

## 授權

[MIT + Commons Clause](LICENSE) — 可自由使用、修改與散布，禁止商業販售。
