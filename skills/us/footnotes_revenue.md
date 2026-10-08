---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_revenue

## Purpose
分析 Note A (Accounting Policies) + Note B (New Guidance)，聚焦收入認列政策與會計準則變動。

## Input
- `current_section`（必填）：Note A + B 全文
- `retry_hint`（選填）

## Instructions
1. Revenue recognition 政策：認列時點（point-in-time vs over-time）、履約義務數量、variable consideration 處理方式
2. 有無政策調整或重分類，引用具體措辭變化
3. 新採用或即將採用的會計準則（ASU/FASB），對財務數字的預期影響
4. 其他重大會計政策變動（存貨計價、折舊方法等）

## Output Format
```json
{
  "revenue_recognition": {
    "policy": "",
    "timing": "point-in-time|over-time|mixed",
    "changed": false,
    "change_detail": ""
  },
  "new_standards": [{"standard": "", "effective_date": "", "impact": ""}],
  "other_policy_changes": [],
  "insufficient_data": false
}
```
