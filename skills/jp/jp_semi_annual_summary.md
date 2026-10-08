---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_semi_annual_summary

## Purpose
分析半期報告書（中間報告書）的財務與業績敘事，聚焦「相對上次有報的變化訊號」，不重複有報已覆蓋的全年分析。

## 原則
- 半期報無 5 年財務摘要表，只有當期（6 個月）與前期同期的比較數字。
- 分析重點是「相對於上次有報的方向變化」，而非絕對數值評價。
- 若未揭露全年預算進度或修正，相關欄位填 null，不推測。

## Input
- `current_section`（必填）：半期報當期 MD&A / 業績章節日文原文（`mda` 或 `business` chapter）
- `prior_section`（選填）：同一公司上一期有報的對應章節原文（YoY 比較基準）
- `retry_hint`（選填）：eval 回饋建議

## Instructions
1. 閱讀 `current_section`，識別以下資訊：
   - 當期半年的主要業績驅動因子（正面 / 負面各列）
   - 管理層對下半期或全年展望的敬語措辭（用敬語強度判斷 commitment）
   - 是否有全年業績預算修正（業績予想の修正）
2. 若有 `prior_section`（前期有報），對比：
   - 業績驅動因子的延續性（是否為同一個主題）
   - 管理層語氣的方向變化（更謹慎 / 更樂觀 / 持平）
3. 評估半期進度：
   - 若原文揭露半期已達全年預算的比例，記錄 `vs_full_year_forecast_progress`
   - 若未揭露，填 null
4. 注意：不分析非半期揭露期間的事件（例如臨時報事件）；不重複 jp_mdna 對全年的分析
5. 所有 JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）

## Output Format
```json
{
  "current_half_performance": "當期上半期業績概述（100 字內）",
  "vs_prior_half": "與前期同期相比的主要差異（50 字內；無前期資料則 null）",
  "vs_full_year_forecast_progress": "全年預算執行進度描述（如「前半期達成全年預算 52%」）或 null",
  "forecast_revision": "業績修正內容（若有）或 null",
  "mgmt_outlook_change": "與上次有報相比，管理層語氣的方向性變化（50 字內）或 null",
  "insufficient_data": false
}
```
