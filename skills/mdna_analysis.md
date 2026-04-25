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
5. Narrative Shift 追蹤（若有 prior_section）

比對管理層用語的演變，特別追蹤以下類型的轉變：

描述性語言（早期）：
  "We continue to focus on / We are investing in / We are exploring"
  → 代表：還在說計畫，沒有成果

績效性語言（成熟）：
  "driving / delivering / visibility / recurring / lifetime value / platform"
  → 代表：已在說成果，市場容易給更高倍數

Re-rate 關鍵詞清單（出現即標記）：
  recurring revenue, visibility, platform transformation,
  lifetime value, operating leverage, margin expansion,
  annualized run rate, contracted backlog

6. 他不講什麼（Silence Analysis）

比對前一年 MD&A 強調的主題，今年是否消失：
- 某個業務去年強調，今年完全不提 → 可能表現不佳
- 某個風險去年詳細說明，今年只用一句帶過 → 可能問題惡化
- 某個 KPI 去年列入，今年從 MD&A 移除 → 可能達不到

## Output Format
```json
{
  "performance_drivers": {"positive": [], "negative": []},
  "non_gaap_changes": "",
  "mgmt_tone": "conservative|neutral|optimistic",
  "mgmt_tone_evidence": "",
  "promises_fulfilled": [],
  "promises_broken": [],
  "narrative_shift": {
    "early_stage_language": [],
    "mature_stage_language": [],
    "shift_detected": false,
    "shift_description": "",
    "rerating_candidate_narrative": false
  },
  "silence_analysis": [],
  "insufficient_data": false
}
```
