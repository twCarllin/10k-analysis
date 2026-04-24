---
skill_version: 1.0
last_modified: 2025-04-23
---

# risk_analysis

## Purpose
分析 SEC 申報文件 Risk Factors 章節（10-K Item 1A / 10-Q Item 1A），萃取風險清單、優先排序與跨期變動。

## Input
- `current_section`（必填）：當年 Item 1A 全文
- `prior_section`（選填）：前一年 Item 1A 全文
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 所有風險標題與 50 字摘要
2. 有 prior_section 時：標記每個風險為 new/removed/reordered/expanded/unchanged
3. expanded 項目引用措辭強度變化（"may" → "will"）
4. 分類：macro/regulatory/operational/financial/legal
5. 前 3 大優先風險（依篇幅 + 排序 + 措辭強度）

## Output Format
```json
{
  "risks": [{"title": "", "summary": "", "type": "", "status": "", "intensity_delta": null}],
  "top_3": [],
  "delta_summary": "",
  "insufficient_data": false
}
```
