---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_customer_supplier

## Purpose
分析台灣上市櫃公司的客戶與供應商集中度、關係人交易對象與議價力。資料來自 `tables_json` 的 T8 與 `concentration`。本 skill 不做算術。

## Input
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（用 T8 `customers_sales`／`customers_purchase` 與 `concentration`、`missing_tables`）
- `ar_market`（選填）：年報產品與原料敘述文字
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 客戶與供應商集中度：只引用 `concentration`（`T8_sales`／`T8_purchase`）既有的 `top1_pct`、`top3_pct`，不自行算術。
2. 兩年度名次與占比變化：由 T8 兩年度欄位讀取，`direction` 填 `rising`／`stable`／`falling`／`unknown`。
3. 關係人客戶／供應商：T8 `relation` 非「無」者，列入 `related_counterparties`。
4. 議價力判斷（bargaining_power）：給出 `strong`／`neutral`／`weak`／`unknown` 與理由。
5. 若有 `ar_market`，說明原料來源與供應狀況。
6. `missing_tables` 內的表不得被引用；T8 缺漏時對應欄位填 null 或 `unknown`。
7. **不做算術**：所有比率讀自 `tables_json` 既有欄位，缺值填 null。
8. JSON value 一律使用繁體中文（列舉值維持英文）；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "customer_concentration": {"top1_pct": null, "top3_pct": null, "direction": "rising|stable|falling|unknown", "note": ""},
  "supplier_concentration": {"top1_pct": null, "top3_pct": null, "direction": "rising|stable|falling|unknown", "note": ""},
  "related_counterparties": [{"name": "", "kind": "customer|supplier", "relation": ""}],
  "bargaining_power": {"vs_customers": "strong|neutral|weak|unknown", "vs_suppliers": "strong|neutral|weak|unknown", "rationale": ""},
  "key_observations": [""],
  "insufficient_data": false
}
```
