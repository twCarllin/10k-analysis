---
skill_version: 1.0
last_modified: 2026-10-09
---

# tw_financial_analysis

## Purpose
分析台灣上市櫃公司兩年度資產負債與損益變化（`tables_json`），並對照管理層在年報的說明是否一致。本 skill 不做算術。

## Input
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（T7a 資產負債、T7b 損益、`derived` 區的各項利潤率；`TwoYearTable.rows[].diff_pct` 直接使用；`metrics` 區（階段 2 指標與 bridge，含公式與輸入值）可直接引用，不重算）
- `ar_mdna`（選填）：年報伍章（財務狀況與經營結果分析）文字
- `ar_letter`（選填）：致股東報告書文字
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 資產負債結構（balance_sheet）：依 T7a 說明結構變化，列出重要變動項目與其 `diff_pct`。
2. 損益（income_statement）：依 T7b 說明各列 YoY；毛利率、營益率、淨利率兩年比較直接讀 `tables_json` 的 `derived` 區。
3. 管理層說明（management_explanation）：比對 `ar_mdna`、`ar_letter` 對變動的解釋與表內數字是否一致；指出未解釋的大變動（`diff_pct` 絕對值 >30% 而文字未提及者）列入 `unexplained_changes`。
4. 整體財務體質（overall_health）：給出 strong / stable / weak，附一句佐證理由。
5. **不做算術**：比率與 `diff_pct` 皆讀既有欄位，缺值填 null。
6. JSON value 一律使用繁體中文；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "balance_sheet": {"summary": "", "notable_changes": [{"item": "", "diff_pct": null, "note": ""}]},
  "income_statement": {"summary": "", "margins": [{"metric": "", "current_pct": null, "prior_pct": null}]},
  "management_explanation": {"consistent": true, "unexplained_changes": [{"item": "", "diff_pct": null}], "summary": ""},
  "overall_health": "strong|stable|weak",
  "overall_health_rationale": "",
  "insufficient_data": false
}
```
