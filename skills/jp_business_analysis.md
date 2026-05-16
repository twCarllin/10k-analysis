---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_business_analysis

## Purpose
分析日本有価証券報告書「事業の内容」章節（jpcrp_cor:DescriptionOfBusinessTextBlock），萃取公司定位、事業結構、終端市場分布、地域分布與子會社組成。

## Input
- `current_section`（必填）：當年「事業の内容」日文原文（TA4 `split_filing_by_ixbrl` 的 `business` key）
- `prior_section`（選填）：前一年同章節日文原文，用於 YoY 結構變化比較
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 公司定位（company_positioning）：公司如何描述自己在產業鏈的角色與核心價值主張？以 2–3 句繁體中文摘要。關鍵日文專有名詞可保留，但整體敘述以繁體中文為主，不大段引用日文原文。
2. 事業部門（business_segments）：依重要性排序各事業部門或事業群，每個含名稱、一句描述、相對收入比重（high/medium/low）。若原文未明確分部門，依事業說明順序歸納。
3. 終端市場分布（end_market_mix）：列出各終端市場名稱、揭露的收入佔比（無則填 null）、趨勢方向（growing/stable/declining）。
4. 地域分布（geographic_mix）：列出各地域銷售比重（若有揭露）。
5. 子會社結構（subsidiaries）：連結子会社主要名稱與業務，無揭露則填空陣列。
6. 有 prior_section 時：比較事業部門增減、市場分類變動、地域重心轉移，填入 `structural_changes`。
7. **劃界（Scope Boundaries）**：本 skill 只描述事業結構現況。不分析研究費用或 R&D 主題（屬 jp_rd_analysis 範圍）；不分析業績 guidance 或管理層前瞻表態（屬 jp_mdna_analysis 範圍）。若事業說明章節夾帶 R&D 或 guidance 資訊，略過不輸出。
8. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "company_positioning": "",
  "business_segments": [
    {"name": "", "description": "", "revenue_weight": "high|medium|low"}
  ],
  "end_market_mix": [
    {"market": "", "pct": null, "trend": "growing|stable|declining"}
  ],
  "geographic_mix": [
    {"region": "", "pct": null}
  ],
  "subsidiaries": [
    {"name": "", "role": ""}
  ],
  "structural_changes": "",
  "insufficient_data": false
}
```
