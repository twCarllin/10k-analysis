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
- `filing_type`（選填）：`"10-K"` | `"10-Q"`；由 orchestrator 注入，預設視為 `"10-K"`
- `quarter`（選填）：`"Q1"` | `"Q2"` | `"Q3"` | `"Q4"`；由 orchestrator 注入
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 業績主要驅動因子（正面/負面各列）
2. Non-GAAP 指標，定義有無改變
3. 前瞻措辭信心程度，引用原文
4. 前期承諾追蹤（有 prior_section 才做）
   用一句話說明前期的承諾在當期的兌現狀況，
   重點是「當期結果」，不是重述前期承諾的內容。
   正確：「AI 業務佔比已達 18%，兌現前期目標」
   錯誤：「前期承諾 AI 佔比達 15%，而本期實際為 18%」
5. Narrative Shift 追蹤（若有 prior_section）

比對管理層用語的演變，特別追蹤以下類型的轉變：

描述性語言（早期）：
  舉例: "We continue to focus on / We are investing in / We are exploring"
  → 代表：還在說計畫，沒有成果

績效性語言（成熟）：
  舉例: "driving / delivering / visibility / recurring / lifetime value
  → 代表：已在說成果，市場容易給更高倍數

財務關鍵詞清單（出現即標記）：
  recurring revenue, visibility, platform transformation,
  lifetime value, operating leverage, margin expansion,
  annualized run rate, contracted backlog

6. Narrative Momentum（若有 prior_section）

量化前後期敘事語言的變化軌跡：
- 計算本期與前期的 early_stage_language 條目數差異 → `early_delta`
- 計算本期與前期的 mature_stage_language 條目數差異 → `mature_delta`
- 判斷 `direction`：
  - `accelerating`：mature_delta > 0 或 early_delta > 0（敘事在成長）
  - `stable`：兩個 delta 都 == 0
  - `decelerating`：mature_delta < 0 或 early_delta < 0（敘事在退縮）

若無 prior_section，momentum 所有欄位填 null。

7. 他不講什麼（Silence Analysis）

比對前一年 MD&A 強調的主題，今年是否消失：
- 某個業務去年強調，今年完全不提 → 可能表現不佳
- 某個風險去年詳細說明，今年只用一句帶過 → 可能問題惡化
- 某個 KPI 去年列入，今年從 MD&A 移除 → 可能達不到

8. 即時競爭壓力偵測（10-Q 全季模式）

僅在 `filing_type` 為 `"10-Q"` 時執行本步驟（含 Q1/Q2/Q3）；10-K 一律輸出 `competitive_pressure_signals: []`。

在 MD&A 全文搜尋以下關鍵字（不限大小寫）：
`pricing pressure`、`competitive environment`、`market share`、`new entrants`、`competitor`、`competitive dynamics`、`increased competition`、`competitive headwinds`

對每個命中段落輸出：
- `summary_zh`：中文摘要（≤ 60 字），中文為主，可保留少量專有名詞英文（如 ASP、CCG、AI 等）
- `quote`：原文 1-2 句（≤ 200 字），verbatim 引用作為審計依據
- `market`：受影響的業務線或市場（中文為主）
- `severity`：`high` / `medium` / `low`
- `vs_prior_quarter`：Q2/Q3 用 `intensifying` / `stable` / `easing`（與 prior_section 比較）；Q1 一律填 `null`（prior 是去年 10-K，季→年比較不對等）

無命中時輸出空陣列（合法結果，不算 insufficient_data）。

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
    "shift_description": "",
    "momentum": {
      "early_delta": null,
      "mature_delta": null,
      "direction": null
    }
  },
  "silence_analysis": [],
  "competitive_pressure_signals": [
    {"summary_zh": "", "quote": "", "market": "", "severity": "high|medium|low", "vs_prior_quarter": "intensifying|stable|easing|null"}
  ],
  "insufficient_data": false
}
```
