---
name: deploy
description: Build and deploy Docker containers (api, worker, pwa) + nginx reload
---

執行以下部署步驟，每步完成後回報結果：

1. **Build containers**
   ```bash
   docker compose build api worker pwa
   ```

2. **Restart services**（不影響 postgres/redis）
   ```bash
   docker compose up -d api worker pwa
   ```

3. **Reload nginx**（避免 502 Bad Gateway）
   ```bash
   docker compose exec nginx nginx -s reload
   ```

4. **驗證服務狀態**
   ```bash
   docker compose ps
   ```

每步如果失敗，立即停止並回報錯誤日誌。
