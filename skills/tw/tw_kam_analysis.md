---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_kam_analysis

## Purpose
解讀台灣上市櫃公司財報查核報告中的關鍵查核事項（KAM），並對照 `tables_json` 指出各事項連到的數字。本 skill 不做算術，不推論查核意見以外的結論。

## Input
- `fs_audit_kam`（必填）：財報查核報告中的關鍵查核事項文字
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（含 T5、T7a／T7b、`missing_tables` 等）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 逐項列出關鍵查核事項（matter）。
2. 說明為何是關鍵（why_key，依會計師原文）與會計師的因應程序（audit_response）。
3. `risk_area` 只能填 `revenue`、`inventory`、`valuation`、`related_party`、`other` 其中之一。
4. 對照 `tables_json`，指出該事項連到哪個數字（linkage_to_numbers）。例：收入截止 → T7b 營業收入；存貨評價 → T5 與 `writedown`。
5. 不得推論查核意見以外的結論。
6. `missing_tables` 內的表不得被引用；無對應表則不列該筆 linkage。
7. **不做算術**：所有數字讀自 `tables_json` 既有欄位，缺值填 null，不自行計算。
8. JSON value 一律使用繁體中文；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "matters": [{"matter": "", "why_key": "", "audit_response": "", "risk_area": "revenue|inventory|valuation|related_party|other"}],
  "linkage_to_numbers": [{"matter": "", "table_ref": "", "observation": ""}],
  "key_observations": [""],
  "insufficient_data": false
}
```
