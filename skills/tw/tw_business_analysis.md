---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_business_analysis

## Purpose
分析台灣上市櫃公司年報的致股東報告書與業務章，整理業務與產品、管理層計畫，並將量化宣稱對照 `tables_json`。本 skill 不做算術。

## Input
- `ar_letter`（必填）：年報致股東報告書文字
- `ar_business`（必填）：年報業務章文字
- `tables_json`（必填）：`tables.py` 預先算好的表集合 JSON 字串（含 T4、T7b、T8、`missing_tables` 等）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 業務與產品摘要（business_summary、products）。
2. 管理層計畫（management_plans）：標明期間（horizon）與是否可量測（measurable）。
3. 敘述 vs 數字（narrative_vs_numbers）：致股東報告書與業務章的量化宣稱，逐條對照 `tables_json`（T7b、T8、T4），status 標 `consistent`／`inconsistent`／`unverifiable`（無法核對）。
4. `missing_tables` 內的表不得被引用；無對應表的宣稱標 `unverifiable`。
5. **不做算術**：所有數字讀自 `tables_json` 既有欄位，缺值填 null，不自行計算。
6. JSON value 一律使用繁體中文（status 為列舉值，維持英文）；語氣依 `agents/analyst_agent.md`（不說「惡化」，說「下降 X%」）。

## Output Format
```json
{
  "business_summary": "",
  "products": [{"name": "", "note": ""}],
  "management_plans": [{"plan": "", "horizon": "", "measurable": true}],
  "narrative_vs_numbers": [{"claim": "", "table_ref": "", "status": "consistent|inconsistent|unverifiable", "note": ""}],
  "key_observations": [""],
  "insufficient_data": false
}
```
