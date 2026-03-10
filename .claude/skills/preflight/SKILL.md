---
name: preflight
description: Pre-deployment checks — lint, type check, tests, and git status
---

部署前檢查，依序執行以下項目，全部通過才報告 READY：

1. **Git status** — 確認沒有未 commit 的變更
   ```bash
   git status --short
   ```

2. **Backend lint + type check**
   ```bash
   cd backend && find . -name '*.py' -not -path './.venv/*' -exec python3 -m py_compile {} +
   ```

3. **Backend tests**
   ```bash
   cd backend && python3 -m pytest --tb=short -q
   ```

4. **Frontend type check**
   ```bash
   cd pwa && npx tsc --noEmit
   ```

5. **Frontend build**（確認能成功編譯）
   ```bash
   cd pwa && npx next build
   ```

每步結果用 ✅ / ❌ 標記。如有失敗項，列出錯誤摘要並建議修復方式。
最後給出總結：READY to deploy 或 NOT READY（附失敗原因）。
