---
skill_version: 1.0
last_modified: 2026-04-29
---

# risk_analysis

## Purpose
分析 SEC 申報文件 Risk Factors 章節（10-K Item 1A / 10-Q Item 1A），萃取風險清單、優先排序與跨期變動。

## 原則
風險分析的唯一目的是：讓投資者知道「現在有哪些風險，各自有多大」。
新增/持平的分類是次要資訊，不應成為呈現的主軸。

## Input
- `current_section`（必填）：當年 Item 1A 全文
- `prior_section`（選填）：前一年 Item 1A 全文
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 列出所有風險項目，每項包含：標題（原文）/ 50 字以內 description / category（macro/regulatory/operational/financial/legal）/ importance（high/medium/low，依篇幅佔比 + 排序位置判斷）
2. 前 3 大風險：依重要性輸出，每個附 rationale 說明為何排前三
3. 若有 prior_section（選填，最後做）：只記錄有實質變化的項目（新增或措辭明顯加重），delta_summary 用一句話描述整體變化方向，不對每個風險標 status

## Output Format
```json
{
  "risks": [
    {"title": "", "description": "", "category": "macro|regulatory|operational|financial|legal", "importance": "high|medium|low"}
  ],
  "top_3": [
    {"title": "", "rationale": ""}
  ],
  "delta_summary": "整體風險輪廓與前期相比的一句話描述（有 prior 才填，否則 null）",
  "insufficient_data": false
}
```
