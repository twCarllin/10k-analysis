---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_tdnet_event

## Purpose
對單一 TDNET 公告（適時開示）進行事件分類與信用影響評估，僅使用公告標題、分類代碼與公司名稱進行判斷，不讀取 PDF 內文。

## Input
- `title`（必填）：TDNET 公告標題，如「2026年3月期 決算短信〔日本基準〕（連結）」
- `category`（必填）：由 `classify_tdnet_title` 自動分類的事件類別，如 `earnings_flash`、`guidance_revision`、`share_buyback` 等
- `company_name`（必填）：公告公司名稱（日文，TDNET 原始格式）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 事件確認（event_category）：依 `category` 欄位對應事件類型，使用以下標準對應規則：
   - `earnings_flash` → 決算短信（季報/全年財報）
   - `guidance_revision` → 業績預測修正
   - `monthly_revenue` → 月次收益揭露
   - `share_buyback` → 自家股購回
   - `share_split` → 股票分割/合并
   - `equity_issuance` → 增資或新股發行
   - `capital_alliance` → 資本業務合作
   - `ma` → 合併收購或股份交換
   - `earnings_other` → 其他業績相關公告
   - `amendment` → 訂正公告（同時標記 is_amendment 為 true）
   - `other` → 其他公告
2. 重要性評估（materiality）：僅根據事件類型與公司規模常識判斷：
   - `high`：決算短信、業績大幅修正、M&A、增資
   - `medium`：業績預測修正（幅度不明）、月次收益、自家股購回
   - `low`：訂正小幅公告、一般資訊揭露
3. 信用面影響（credit_impact）：評估此類型事件對公司信用評分的潛在方向：
   - 決算短信本身屬中性（不知道內容好壞）→ `"neutral"`
   - 增資、M&A 依情境 → `"unclear"`（無 PDF 無法判斷方向）
   - 自家股購回 → 通常正面 → `"positive"`
   - 若確定無法判斷 → `"unclear"`
4. 訂正標記（is_amendment）：若 `category` 為 `amendment` 或標題含「（訂正）」「（更正）」前綴，標記為 true。
5. 事件摘要（event_summary）：以 1–2 句繁體中文描述此公告的事件意義，例如「本公告為全年度決算短信，揭露財務結果，為投資人每年最重要的觀察指標之一。」不補充 PDF 內未揭露的具體數字。
6. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## 注意事項
- 本 skill 不讀取 PDF 內容，僅依標題、分類代碼與公司名稱作出評估
- 若 `title` 或 `category` 不足以判斷，在相關欄位填 `null` 或 `"unclear"`，不可捏造具體數字或業績
- 不重複分析 PDF 層級的財務細節（屬 jp_financial_analysis / jp_tdnet_flash 未來 skill 範圍）

## Output Format

```json
{
  "event_category": "決算短信",
  "materiality": "high",
  "credit_impact": "neutral",
  "is_amendment": false,
  "event_summary": "本公告為年度決算短信，為投資人每年最重要的財務揭露事件，需後續讀取 PDF 確認具體業績。",
  "insufficient_data": false
}
```
