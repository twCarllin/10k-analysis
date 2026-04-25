---
skill_version: 1.0
last_modified: 2025-04-23
---

# rerate_signal

## Purpose
整合結構分析、三表矛盾分析、管理層敘事分析，
判斷公司是否符合 Re-rate 或 De-rate 條件，
輸出機構級的投資判斷框架與追蹤清單。

核心邏輯（來自機構分析師框架）：
Re-rate = 結構在變（Segment）+ 品質在變（Margin/Cash）+ 敘事在變（MD&A）
三個條件同時成立才算訊號，任何單一條件都不夠。

## Input
- segment_summary（必填）：segment_trend agent 輸出的 JSON 字串
- three_statement_summary（必填）：three_statement_cross agent 輸出的 JSON 字串
- mdna_summary（必填）：mdna_agent 輸出的 JSON 字串
- financial_summary（必填）：financial_agent 輸出的 JSON 字串
- retry_hint（選填）

## Instructions

### Step 1：從上游事實判定三個 Re-rate 條件

上游 agent 只輸出事實（數字、列表、原文引述），所有投資判斷由本 skill 根據以下規則執行。

條件 A：結構在變（Segment）
- 來源：segment_summary.segment_table
- 判斷規則：
  1. 找出所有 margin_quality == "high" 且 direction == "rising" 的 segment
  2. 其中任一 segment 的 revenue_pct 在最近 2 年內上升超過 5 個百分點 → structure_changing = true
  3. 否則 → structure_changing = false
  4. 若 segment_table 為空或 insufficient_data == true → false

條件 B：品質在變（Margin / Cash）
- 來源：three_statement_summary.overall_signals 和 checks
- 判斷規則：
  1. 計算 overall_signals 中 signal_type == "bullish" 的數量（B）和 "bearish" 的數量（R）
  2. B > R 且 R == 0 → quality_changing = true
  3. 否則 → quality_changing = false
  4. 若 checks 中 revenue_vs_cashflow.signal == "bearish" → 強制 false（現金流矛盾一票否決）

條件 C：敘事在變（MD&A Narrative Shift）
- 來源：mdna_summary.narrative_shift.mature_stage_language 和 early_stage_language
- 判斷規則：
  1. 計算 mature_stage_language 條目數（M）
  2. M >= 3 → narrative_changing = true
  3. 否則 → narrative_changing = false
  4. 若 mdna_summary 無 narrative_shift 欄位 → false

### Step 2：判斷 Re-rate / De-rate 狀態

全部三個條件成立 → RERATING（強烈訊號）
兩個條件成立    → WATCH（持續追蹤）
一個條件成立    → EARLY（太早下結論）
零個條件成立，且 De-rate 觸發條件任一成立 → DERATING
零個條件成立，且無 De-rate 觸發條件         → NEUTRAL

De-rate 觸發條件（任一成立即降級）：
- three_statement_summary.overall_signals 中 bearish 數量 >= 2
- mdna_summary.promises_broken 連續兩期有項目
- financial_summary.quality_flags 數量 >= 3
- segment_summary.segment_table 中任一 margin_quality == "high" 的 segment direction == "falling"

### Step 3：建立追蹤清單（Monitoring Checklist）

文章框架：分析師不停在「判斷」，會轉成「投資行動」

針對 RERATING / WATCH 的公司，輸出：
① 下一季需追蹤的指標（具體，可驗證）
   例：新業務營收佔比是否超過 50%？FCF conversion 是否回升？
② 驗證點（Validation Trigger）
   如果 [具體條件] 成立 → thesis 正確（加碼/持有）
   如果 [具體條件] 不成立 → thesis 失敗（減碼/出場）

### Step 4：分類為 Bull / Bear Case

沿用文章的決策層框架：

Bull Case（投資期）需同時符合：
- Opex ↑ 有對應的新業務成長
- CapEx ↑ 毛利未崩
- CFO 穩定或上升
- 庫存、AR 無異常

Bear Case（惡化期）任一符合即標記：
- 毛利下降 + 庫存上升
- AR 暴增 + 營收未加速
- CFO 明顯下降
- CapEx ↑ 但無回報

## Output Format
```json
{
  "rerating_conditions": {
    "structure_changing": true,
    "quality_changing": true,
    "narrative_changing": false,
    "conditions_met": 2
  },
  "verdict": "RERATING|WATCH|EARLY|NEUTRAL|DERATING",
  "verdict_rationale": "結構與品質條件已成立，MD&A 敘事尚未出現 recurring/visibility 等關鍵詞，建議持續追蹤",
  "bull_case": {
    "valid": true,
    "conditions_met": ["Opex ↑ + SaaS 成長", "毛利率維持"],
    "conditions_missing": []
  },
  "bear_case": {
    "valid": false,
    "triggered_by": []
  },
  "monitoring_checklist": [
    "新業務（SaaS+AI）合計營收佔比是否在下一季超過 55%",
    "整體毛利率是否持續在 44% 以上",
    "FCF conversion 是否回升至 0.9 以上"
  ],
  "validation_triggers": {
    "thesis_confirmed": "下一季 AI segment 佔比超過 20% + 整體毛利率上升",
    "thesis_failed": "下一季 AI 佔比停滯或毛利率下滑超過 2 個百分點"
  },
  "derating_flags": [],
  "insufficient_data": false
}
```
