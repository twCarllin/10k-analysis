---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_strategy

## Purpose
分析日本有価証券報告書「経営方針、経営環境及び対処すべき課題等」章節（jpcrp_cor:BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock），萃取中長期經營方針、具體 KPI 目標與當前課題。

## Input
- `current_section`（必填）：當年「経営方針・課題」章節日文原文（TA4 `split_filing_by_ixbrl` 的 `strategy` key）
- `prior_section`（選填）：前一年同章節日文原文，用於策略方向變化比較
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 願景與經營方針（vision）：管理層如何定義公司長期方向與核心原則？以 1–2 句繁體中文摘要。
2. 中長期目標（mid_term_targets）：列出所有具體目標，每個元素含：
   - `kpi`：KPI 名稱（如「連結営業利益率」、「ROE」）
   - `target_value`：目標數字或描述（如「10%以上」、「グローバルシェア拡大」），無則 null
   - `deadline`：目標年度或年份（如「2027年3月期」），無則 null
3. 当前課題（current_challenges）：管理層明示的「対処すべき課題」——列出具體問題陳述，以繁體中文描述。
4. 行動方案（action_items）：管理層提出的具體應對措施或計畫，每項一句話。
5. 可量化程度（measurability）：評估目標整體的量化程度——`"quantitative"`（多數有具體數字）/ `"qualitative"`（多數為方向性描述）/ `"mixed"`（兩者均有）。
6. 若有 prior_section（選填）：比較策略重心轉移，填入 `strategy_shift` 一句話描述。
7. **劃界（Scope Boundaries）**：本 skill 只萃取未來方向相關內容。不分析已實現的業績數字（屬 jp_mdna_analysis 範圍）；不描述現行事業結構或終端市場分布（屬 jp_business_analysis 範圍）；若 strategy 章節措辭與 MD&A 高度重疊，只萃取「未來方向」相關句子，不重複描述歷史業績。
8. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "vision": "",
  "mid_term_targets": [
    {"kpi": "", "target_value": null, "deadline": null}
  ],
  "current_challenges": [],
  "action_items": [],
  "measurability": "quantitative|qualitative|mixed",
  "strategy_shift": "",
  "insufficient_data": false
}
```
