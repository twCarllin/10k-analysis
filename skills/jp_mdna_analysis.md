---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_mdna_analysis

## Purpose
分析日本有価証券報告書「経営者による財政状態、経営成績及びキャッシュ・フローの状況の分析」章節（jpcrp_cor:ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock），萃取業績驅動因子、管理層語氣與前瞻承諾強度。

## Input
- `current_section`（必填）：當年 MD&A 章節日文原文（TA4 `split_filing_by_ixbrl` 的 `mda` key）
- `prior_section`（選填）：前一年同章節日文原文，用於前期承諾追蹤
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 業績主要驅動因子（performance_drivers）：分別列出正面與負面因子，以繁體中文描述，數字說話。
2. 管理層整體語氣（mgmt_outlook）：conservative / neutral / optimistic，引用 1–2 句原文當佐證。
3. 前瞻承諾強度（commitment_strength）：依以下敬語層次判斷：
   - 「達成すべく取り組んでまいります」→ `"high"`（明確承諾）
   - 「達成に向けて努力してまいります」→ `"medium"`（努力承諾）
   - 「目指してまいります」→ `"low"`（方向性表態）
   - 若無前瞻陳述 → `commitment_strength: null`
4. 前瞻訊號（forward_signals）：列出管理層提及的具體 KPI 目標、期間或數字（若有）。
5. 若有 prior_section（選填）：追蹤前期承諾的兌現狀況，填入 promises_fulfilled / promises_broken。用一句話描述兌現結果，不重述前期承諾內容。
6. **劃界（Scope Boundaries）**：本 skill 只分析已實現業績的原因與管理層對近期展望的表態。不分析個別風險條目（屬 jp_risk_analysis 範圍）；不重述 strategy 章節的中長期方針（屬 jp_strategy_analysis 範圍）。若 MD&A 章節夾帶中長期策略方向描述，略過不輸出。
7. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "performance_drivers": {
    "positive": [],
    "negative": []
  },
  "mgmt_outlook": "conservative|neutral|optimistic",
  "mgmt_outlook_evidence": "",
  "commitment_strength": "high|medium|low|null",
  "forward_signals": [],
  "promises_fulfilled": [],
  "promises_broken": [],
  "insufficient_data": false
}
```
