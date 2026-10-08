---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_governance_flags

## Purpose
標示台灣上市櫃公司的公司治理旗標：股權質押、股東結構、董事會、背書保證與資本行動。資料來自 `tables_json` 的 T10、T9 與年報治理段落。本 skill 只比較不計算。

## Input
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（用 T10 `pledges`、`top_shareholders`、T9 `guarantees_loans`、`missing_tables`）
- `ar_governance`（選填）：年報公司治理文字（董事會、獨立董事）
- `ar_capital`（選填）：年報資本與股務文字
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 質押（pledge）：讀 `pledges` 的 `status` 與 `max_pledge_pct`。質押比率 >30% 標 `watch`，>50% 標 `alert`，其餘標 `normal`。門檻寫在本 skill 內，只比較不計算；`status` 非 `rows` 時 `max_pledge_pct` 填 null，`flag` 標 `normal`，並在 note 說明狀態。
2. 股東結構（ownership）：前十大股東結構，以及 `relation_notes` 顯示的家族關係。
3. 董事會（board）：依 `ar_governance` 說明組成與獨立董事；無資料標 `unknown`。
4. 背書保證（guarantees）：對象與佔淨值比率，讀 T9 `max_pct_of_net_worth`；無揭露標 `none_disclosed`。
5. 資本行動（capital_actions）：依 `ar_capital` 列出增資、公司債、限制員工權利新股等。
6. `missing_tables` 內的表不得被引用。
7. **不做算術**：所有比率讀自 `tables_json` 既有欄位，缺值填 null，不自行計算。
8. JSON value 一律使用繁體中文（列舉值維持英文）；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "pledge": {"status": "rows|none|external_reference|unknown", "max_pledge_pct": null, "flag": "normal|watch|alert", "note": ""},
  "ownership": {"structure_note": "", "family_relations_note": "", "flag": "normal|watch"},
  "board": {"independence_note": "", "flag": "normal|watch|unknown"},
  "guarantees": {"note": "", "flag": "normal|watch|none_disclosed"},
  "capital_actions": [{"item": "", "note": ""}],
  "key_observations": [""],
  "insufficient_data": false
}
```
