---
name: finish-all-jobs
description: Read TODO.md, implement each uncompleted task one by one, verify, commit, and continue until all done.
---

讀取 TODO.md。
從上到下找出第一個狀態為未完成 `[ ]` 的任務，並嚴格執行以下迴圈：

1. **實作**：編寫或修改達成該任務所需的程式碼。
2. **驗證**：執行相關的測試或語法檢查，確保代碼無誤。
3. **標記**：如果驗證通過，請修改 TODO.md，將該任務標記為完成 `[x]`。
4. **存檔**：使用 git commit 提交這次的變更（請寫明簡短的 commit message）。
5. **繼續**：自動尋找下一個未完成的任務，並重複步驟 1 到 4。

⚠️ 停止條件：
- 當 TODO.md 中所有任務都標記為 `[x]` 或是因為驗證未通過而略過時，請停止並回報「任務全數完成」。
- 如果在「驗證」階段遇到無法解決的錯誤（嘗試修復超過 3 次失敗），保留未完成狀態，暫時略過該項目並加上原因。
