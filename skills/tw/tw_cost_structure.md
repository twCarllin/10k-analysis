---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_cost_structure

## Purpose
分析台灣上市櫃公司年報＋財報預先整理的成本與費用表（`tables_json`），解讀成本組成、費用性質、存貨與營業槓桿。本 skill 不做算術，所有比率皆讀自 `tables_json` 既有欄位。

## Input
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（T1–T7b、`parent_cost_coverage`、`missing_tables`；含各成本項占營業成本比、占營收比、YoY）
- `ar_market`（選填）：年報產品與原料敘述文字
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 先讀 `parent_cost_coverage`：≥0.8 → 以 T1–T3 為主；0.3–0.8 → T1–T3 只代表母公司，結論須標「母公司口徑」；<0.3 或 None → 不引用 T1–T3，改以 T4／T5／T7b 分析，並在 `coverage_note` 說明。`coverage_basis` 依序填 `parent`／`consolidated`／`annual_report_only`。
2. 成本組成（cost_composition）：直接原料、直接人工、製造費用的占比與 YoY。
3. 費用性質（expense_nature）：員工福利、折舊、攤銷占營收比。
4. 存貨（inventory）：結構與跌價說明。
5. T6 有值時，給單位成本／單價走勢（unit_economics）；T6 無值則留空陣列。
6. 營業槓桿（operating_leverage）：營收 YoY 對營業利益 YoY，數字由 T7b 讀取。
7. `missing_tables` 內的表不得被引用。
8. **不做算術**：所有比率、YoY 一律讀 `tables_json` 內既有欄位，缺值填 null，不自行計算。
9. JSON value 一律使用繁體中文；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "coverage_basis": "parent|consolidated|annual_report_only",
  "coverage_note": "",
  "cost_composition": [{"item": "", "share_pct": null, "yoy_pct": null, "note": ""}],
  "expense_nature": [{"item": "", "pct_of_revenue": null, "note": ""}],
  "inventory": {"structure_note": "", "writedown_note": ""},
  "unit_economics": [{"product": "", "implied_asp": null, "implied_unit_cost": null, "note": ""}],
  "operating_leverage": {"revenue_yoy_pct": null, "operating_income_yoy_pct": null, "summary": ""},
  "key_observations": [""],
  "insufficient_data": false
}
```
