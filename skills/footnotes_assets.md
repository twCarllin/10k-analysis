---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_assets

## Purpose
分析 Note M (Inventories) + Note N (PP&E) + Note O (Goodwill) + Note R (Financial Instruments)，聚焦資產品質與估值風險。

## Input
- `current_section`（必填）：Note M + N + O + R 全文
- `retry_hint`（選填）

## Instructions
1. 存貨計價方法（LIFO/FIFO）、LIFO reserve 金額與變動
2. PP&E 資本支出趨勢、折舊方法
3. 商譽餘額、各報告單位分配、減損測試假設（折現率、成長率）
4. 商譽公允價值超過帳面價值的 cushion
5. 其他無形資產攤銷
6. 金融工具公允價值層級、衍生品使用

## Output Format
```json
{
  "inventory": {"method": "", "lifo_reserve": "", "lifo_reserve_change": ""},
  "ppe": {"capex": "", "depreciation_method": ""},
  "goodwill": {
    "total": "",
    "by_unit": [{"unit": "", "amount": ""}],
    "impairment_test": {"discount_rate": "", "growth_rate": "", "cushion": ""},
    "cumulative_impairment": ""
  },
  "intangibles_amortization": "",
  "financial_instruments": "",
  "insufficient_data": false
}
```
