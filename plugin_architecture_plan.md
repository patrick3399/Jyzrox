> **ARCHIVED** — This planning document has been fully implemented. See `backend/plugins/` for actual code.

# Jyzrox Plugin (擴充套件) 系統架構規劃草案

目前的程式碼庫（檢視結果）中，**完全沒有任何 `plugin` 相關的基礎建設或介面 (Interfaces)**。所有的來源（如 E-Hentai 爬蟲與 gallery-dl 呼叫）都是 Hard-code 寫死在 `routers/` 與 `services/` 裡的。

為了解決這個未來計畫，我們必須為 FastAPI + ARQ 後端設計一套靈活且安全的 Plugin 系統。以下是針對 Jyzrox 專案特性所規劃的 Plugin 架構藍圖：

## 1. Plugin 系統的目標與定位

在一個大一統的圖庫系統中，Plugin 應該要能解決以下三種場景：
1.  **Metadata Scraper (元資料刮削器)**：能夠透過給定的一個 ID 或是網址（例如 `fakku:1234`），讓 Plugin 連線至對應網站並回傳標準化的 Metadata（標題、標籤、語言等）。
2.  **Downloader (自訂下載引擎)**：對於某些 `gallery-dl` 支援不佳，或是需要高度客製化行為（例如 E-Hentai 的 H@H 節點邏輯、Pixiv 的多幀動圖合成）的網站，提供原生的 Python 下載器介面。
3.  **Tagger (打標器)**：除了內建的 WD14 ONNX 推論，允許載入外部 API（例如呼叫 OpenAI Vision 或 Google Cloud Vision）來輔助自動標籤。

## 2. 核心架構設計 (Python Entry Points)

由於 Jyzrox 完全基於 Python，業界標準的 Plugin 實作方式是透過 `pluggy` 或是原生的 `Subclassing` + `entry_points`。考慮到易用性與隔離性，建議採用 **Base Class Registry (基底類別註冊制)**。

### 目錄結構規劃
```text
backend/
├── plugins/               <-- 所有的 Plugin 放在這個獨立資料夾
│   ├── __init__.py
│   ├── base.py            <-- 定義 Plugin 必須實作的 Abstract Base Classes (ABC)
│   ├── exhentai.py        <-- 將現有的 eh_client 封裝為標準 plugin 形式
│   ├── pixiv.py           <-- 開發中的 Pixiv 專用下載/刮削器
│   └── custom_booru.py    <-- 第三方擴充
```

### 介面設計 (Interface Design)

Plugin 應該要繼承一個定義良好的基底類別，例如 `BaseGalleryPlugin`：

```python
# plugins/base.py
from pydantic import BaseModel
from typing import AsyncGenerator

class GalleryMetadata(BaseModel):
    title: str
    tags: list[str]
    pages: int
    source: str
    source_id: str

class BaseGalleryPlugin:
    # 識別這個 Plugin 能處理哪些 URL 或前綴 (例如: "pixiv:", "eh:")
    source_prefix: str 
    
    async def fetch_metadata(self, source_id: str) -> GalleryMetadata:
        """根據給定的 ID 抓取圖庫資訊"""
        raise NotImplementedError()
        
    async def download_pages(self, source_id: str) -> AsyncGenerator[bytes, None]:
        """非同步 Generator，產出每一頁的圖片 Byte 資料供 Worker 寫入 CAS"""
        raise NotImplementedError()
```

## 3. 與現有 ARQ 背景任務系統的整合

現有的 `worker.py` 高度依賴 `gallery-dl` 的 subprocess 呼叫。導入 Plugin 系統後，下載任務的邏輯將改為**動態路由 (Dynamic Routing)**：

```python
# worker.py 想像的重構邏輯：
from plugins import plugin_manager 

async def download_job(ctx: dict, url_or_uri: str, ...):
    # 1. 判斷是否為 Plugin 支援的網址
    plugin = plugin_manager.get_handler_for_url(url_or_uri)
    
    if plugin:
        # 使用原生 Plugin 引擎下載，避免開 Subprocess
        metadata = await plugin.fetch_metadata(source_id)
        # ... 寫入資料庫 ...
        async for image_bytes in plugin.download_pages(source_id):
             # 寫入 CAS
             cas_hash = store_blob_in_cas(image_bytes)
             create_symlink(cas_hash)
             
    else:
        # 2. 如果沒有原生 Plugin 處理，退回 (Fallback) 呼叫 gallery-dl
        await run_gallery_dl_subprocess(url_or_uri)
```

## 4. 前端 (PWA) 的動態表單支援

當使用者想要新增一個來源（例如配置 Pixiv 的 Refresh Token，或是特定 Booru 的 API Key）時，PWA 不能寫死這些欄位。

*   **後端 API**：需要一個 `GET /api/plugins` 路由，Plugin 會宣告它需要的設定欄位（JSON Schema 格式）。
    *   例如：`{"pixiv": {"fields": [{"name": "refresh_token", "type": "password", "required": True}]}}`
*   **前端實作**：Next.js PWA 在「設定頁面」會動態讀取這個 JSON Schema，並渲染出對應的輸入框，最後將使用者的輸入存入資料庫的 `credentials` 表 (`models.py` 中現有此表！非常完美的預見性設計)。

## 5. 安全性考量 (Security Constraints)

若未來開放讓使用者自行丟 Python 檔案進 `/plugins` 資料夾載入，會有極大的 **RCE (Remote Code Execution)** 風險。
1.  **現階段解法**：僅允許系統管理員將 `.py` 檔案放入特定的伺服器路徑 `/backend/plugins`，重啟 FastAPI / Worker 生效。不開放 Web UI 上傳 Plugin 腳本。
2.  **沙盒執行 (如果需要 Web 上傳)**：如果堅持要透過網頁上傳 Plugin，必須改用 WebAssembly (Wasm) 或是在 Docker 內再開一個低權限的隔離 Subprocess 執行 Python，這會大幅增加開發成本。強烈建議維持「本機檔案系統載入」的模式。

## 總結與下一步行動

專案架構（例如已經設計好的 `credentials` 表）顯示已經在為擴充性鋪路。

**如果要開始動手實作 Plugin 系統，建議的步驟為：**
1.  建立 `plugins/base.py`，定義好 `fetch_metadata` 與 `download` 等非同步介面與 Pydantic 回傳模型。
2.  建立 `plugins/manager.py`，實作一個動態載入 `.py` 檔案並註冊到字典的管理器。
3.  **第一次重構 (Proof of Concept)**：將現存的 `eh_downloader.py` 與 `eh_client.py` 封裝，實作成系統的第一個「原生 Plugin」，驗證架構是否順暢。
