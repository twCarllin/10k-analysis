# 工程回顧記錄（RETRO）

本檔案記錄每次 code review 發現重大問題後的根因分析與可行動教訓，供團隊累積知識使用。

---

## 2026-04-24 Retro — section_splitter.py

### 問題清單

| # | 嚴重度 | 問題摘要 | 根因分類 |
|---|--------|---------|---------|
| 1 | 🔴 | `_is_valid()` 10-Q 分支用 `any` 而非 `all` 檢查 critical sections，導致 item2 (MD&A) 單獨缺失不會觸發 fallback | 疏忽 + 驗證盲點 |
| 2 | 🔴 | `_toc_guided_split()` 最終組裝 result 時未過濾 `target_sections`，非目標 key 可能污染輸出 | 疏忽 + 驗證盲點 |

### 教訓

1. **any/all 語意要對齊「缺一不可」還是「有一即可」**
   - 根因：critical sections 的語意是「所有必要欄位都存在才算有效」（缺一不可），但開發者沿用了「有找到東西就繼續」的 `any` 直覺，兩者方向相反卻不會在語法層面報錯，容易在快速實作時寫錯。
   - 預防：撰寫 validation guard 時，先用自然語言寫一句「通過條件是 ___ 都滿足（all）還是任一滿足（any）」，再轉成程式碼。測試案例必須包含「只缺少一個 critical field 但其他都存在」的情境，確保 guard 能攔截。

2. **輸入端有過濾規格，輸出端必須同步套用**
   - 根因：在多階段管道中，開發者在解析階段（ToC parsing）已取得正確 keys，但在最終組裝（result 建構）時忘了對照 `target_sections` 做 intersection，導致中間產物的非目標 key 滲漏到輸出。「只想到主流程、忘了邊界條件」是多階段管道的常見疏忽。
   - 預防：撰寫任何 pipeline 的最後組裝步驟時，加一個明確的白名單過濾（例如 `{k: v for k, v in result.items() if k in target_sections}`）作為防禦層，而非依賴上游每個階段都不會帶入雜訊。測試案例必須驗證「result keys 嚴格等於 target_sections，不多不少」。

### 行動項目

- [ ] 在 `section_splitter.py` 相關測試中補充「10-Q 僅缺少 item2 但含有其他 sections」的測試案例，驗證 `_is_valid()` 確實回傳 False
- [ ] 在 `section_splitter.py` 相關測試中補充「ToC 含有非目標 section」的測試案例，驗證 `_toc_guided_split()` 輸出的 result keys 嚴格等於 target_sections
- [ ] 建立 code review checklist 項目：「validation guard 使用 any/all 時，是否對齊缺一不可 vs 有一即可的語意」
- [ ] 建立 code review checklist 項目：「pipeline 最終組裝是否有白名單過濾，確保輸出不含非目標 key」
