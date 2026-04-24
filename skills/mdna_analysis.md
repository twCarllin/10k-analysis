---
skill_version: 1.0
last_modified: 2025-04-23
---

# mdna_analysis

## Purpose
分析 SEC 申報文件 MD&A 章節（10-K Item 7 / 10-Q Item 2），萃取業績驅動因子、管理層語氣與前瞻承諾。

## Input
- `current_section`（必填）：當年 Item 7 全文
- `prior_section`（選填）：前一年 Item 7 全文
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 業績主要驅動因子（正面/負面各列）
2. Non-GAAP 指標，定義有無改變
3. 前瞻措辭信心程度，引用原文
4. 有 prior_section 時：上期承諾本期是否兌現

## Output Format
```json
{
  "performance_drivers": {"positive": [], "negative": []},
  "non_gaap_changes": "",
  "mgmt_tone": "conservative|neutral|optimistic",
  "mgmt_tone_evidence": "",
  "promises_fulfilled": [],
  "promises_broken": [],
  "insufficient_data": false
}
```
