---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_pension

## Purpose
分析 Note G (Pension and Other Postretirement Benefits)，聚焦退休金資金缺口與精算假設。

## Input
- `current_section`（必填）：Note G 全文
- `retry_hint`（選填）

## Instructions
1. 確定給付義務（PBO/ABO）與計畫資產公允價值，資金缺口
2. 精算假設：折現率、預期資產報酬率、薪資成長率
3. 假設變動對義務的敏感度
4. ��畫資產配置（股票/債券/其他）
5. 未認列精算損益金額
6. 未來預計提撥金額
7. 淨退休金費用組成

## Output Format
```json
{
  "funded_status": {"pbo": "", "plan_assets": "", "deficit": ""},
  "assumptions": {"discount_rate": "", "return_on_assets": "", "salary_growth": ""},
  "unrecognized_losses": "",
  "asset_allocation": [{"category": "", "pct": ""}],
  "expected_contributions": "",
  "net_periodic_cost": "",
  "insufficient_data": false
}
```
