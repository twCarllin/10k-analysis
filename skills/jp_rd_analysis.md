---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_rd_analysis

## Purpose
分析日本有価証券報告書「研究開発活動」章節（jpcrp_cor:ResearchAndDevelopmentActivitiesTextBlock），萃取 R&D 主題、研究費用、主要項目與合作關係。

## Input
- `current_section`（必填）：當年「研究開発活動」章節日文原文（TA4 `split_filing_by_ixbrl` 的 `rd` key）
- `prior_section`（選填）：前一年同章節日文原文，用於主題變化比較
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. R&D 主題（themes）：列出本期研究開發的主要技術方向或領域，每項一句繁體中文描述。
2. 研究費用佔比（rd_expense_pct）：若章節內揭露研究開発費金額與營收數字，計算佔比並填入（如 `"3.2%"`）；若未揭露比例且無法直接計算，填 `null`，不要推算或從其他章節補充。若只揭露金額未揭露佔比，填入 `null` 並在 themes 中附帶說明金額。
3. 主要研究項目（key_projects）：列出具體研究項目名稱與一句描述（以繁體中文）。
4. 產學合作（partnerships）：列出共同研究機構或企業名稱，無則填空陣列。
5. 專利布局（patents）：若章節提及專利申請或佈局方向，以一句話摘要；無揭露則填 null。
6. 若有 prior_section（選填）：比較主題演變，填入 `theme_changes` 一句話描述。
7. **劃界（Scope Boundaries）**：本 skill 只分析研究開發章節揭露的內容。不描述事業部門結構或終端市場（屬 jp_business_analysis 範圍）。若 R&D 章節文字過短（如僅 200–300 字），直接輸出現有資訊，不補充外部知識或推論。
8. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "themes": [],
  "rd_expense_pct": null,
  "key_projects": [
    {"name": "", "description": ""}
  ],
  "partnerships": [],
  "patents": null,
  "theme_changes": "",
  "insufficient_data": false
}
```
