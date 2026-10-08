---
skill_version: 1.0
last_modified: 2025-04-23
---

# cross_year_compare

## Purpose
跨年度 + 跨維度比較分析，找出矛盾與印證訊號。

## Input
- `current_analysis`（必填）：當年所有 agent 分析結果 JSON
- `prior_analysis`（選填）：前一年所有 agent 分析結果 JSON
- `retry_hint`（選填）：eval 回饋的改善指示

## 分析立場
當期（current）是分析主角。
prior 的作用只有一個：提供對照基準，用來說明「當期的數字或敘述有什麼意義」。

正確：「本期營收成長 12%，較前期的 8% 加速」
錯誤：「前期營收成長 8%，本期則達到 12%」

所有結論句應以當期為主詞，前期數字作為括號補充或修飾語。
`delta_summary` 與 `cross_checks` 的每一條都應遵守此原則。

## Instructions
prior_analysis 為 null 時只做 current 摘要，delta 欄位填 null。
否則：
1. 跨維度矛盾（MD&A 說成長但財務毛利下滑）
2. 跨維度印證（Risk 新增，Business 有對應動作）
3. 管理層敘述 vs 數字一致性
4. quality_flags 跨年升降（會計品質惡化訊號）

## Output Format
```json
{
  "cross_checks": [{"dimensions": [], "finding": "", "implication": "", "direction": "positive|negative|neutral"}],
  "mgmt_credibility": "high|medium|low",
  "mgmt_credibility_reason": "",
  "quality_trend": "improving|stable|deteriorating",
  "overall_direction": "improving|stable|deteriorating",
  "insufficient_data": false
}
```
