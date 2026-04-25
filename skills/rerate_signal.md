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

### Step 1：評估三個 Re-rate 條件

條件 A：結構在變（Segment）
- 來源：segment_summary.rerating_candidate_structure
- 判斷：高毛利業務佔比持續上升，趨勢已持續 2 年以上

條件 B：品質在變（Margin / Cash）
- 來源：three_statement_summary.rerating_candidate_quality
- 判斷：dominant_signal == "bullish"，三表無重大矛盾

條件 C：敘事在變（MD&A Narrative Shift）
- 來源欄位：mdna_summary.narrative_shift.mature_stage_language 和 early_stage_language
- 判斷規則（由本 skill 自行判定，mdna 只提供事實）：
  1. 計算 mature_stage_language 條目數（M）和 early_stage_language 條目數（E）
  2. M >= 3 且 M > E → narrative_changing = true
  3. 否則 → narrative_changing = false
  4. 若 mdna_summary 無 narrative_shift 欄位 → narrative_changing = false
- 特別關注的績效性語言（出現在 mature 清單中權重較高）：
  recurring revenue / visibility / platform / lifetime value /
  operating leverage / margin expansion

### Step 2：判斷 Re-rate / De-rate 狀態

全部三個條件成立 → RERATING（強烈訊號）
兩個條件成立    → WATCH（持續追蹤）
一個條件成立    → EARLY（太早下結論）
零個條件成立，且 De-rate 觸發條件任一成立 → DERATING
零個條件成立，且無 De-rate 觸發條件         → NEUTRAL

De-rate 觸發條件（任一成立即降級）：
- three_statement_summary.dominant_signal == "bearish"
- mdna_summary.promises_broken 連續兩期有項目
- financial_summary.quality_flags 有 "revenue 數字可信度降低"
- segment_summary.structural_shift == "downgrading"

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
