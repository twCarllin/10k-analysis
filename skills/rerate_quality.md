---
skill_version: 1.0
last_modified: 2025-04-25
---

# rerate_quality

## Purpose
判斷公司營收品質是否正在改善：利潤率與現金流趨勢是否向好。

## Input
- three_statement_summary（必填）：three_statement_cross agent 輸出的 JSON 字串
- retry_hint（選填）

## Instructions

根據 three_statement_summary 的事實數據，判斷營收品質是否在改善。

判斷規則：
1. 計算 overall_signals 中 signal_type == "bullish" 的數量（B）和 "bearish" 的數量（R）
2. B > R 且 R == 0 → true
3. 否則 → false
4. 若 checks 中 revenue_vs_cashflow.signal == "bearish" → 強制 false（現金流矛盾一票否決）

論述撰寫規則：
- 全部使用繁體中文，嚴禁引用英文原文
- 用具體數字佐證（利潤率、現金流、成長率）
- 控制在 3-5 句內，直接說結論和依據

## Output Format
```json
{
  "result": false,
  "rationale": "正面訊號 2 個（毛利率回升、庫存去化），但負面訊號 1 個（資本支出回報不明）。營業現金流低於淨利，現金流品質存疑，一票否決。整體品質改善跡象存在但尚不穩固。"
}
```
