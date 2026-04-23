---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_receivables

## Purpose
分析 Note L (Receivables) + Note Q (Debt)，聚焦應收帳款證券化與債務結構。

## Input
- `current_section`（必填）：Note L + Q 全文
- `retry_hint`（選填）

## Instructions
1. 應收帳���證券化/保理安排：額度、動用金額、未售出但作為擔保的金額
2. 客戶應收帳款銷售金額與趨勢
3. 債務結構：短期/長期、到期時程、利率
4. 債務契約（covenants）與遵循狀況
5. 信用額度使用狀況
6. 對現金流報表的影響（off-balance sheet 效果）

## Output Format
```json
{
  "securitization": {
    "facility_size": "",
    "drawn_amount": "",
    "unsold_collateral": ""
  },
  "customer_receivables_sold": "",
  "debt_structure": [{"type": "", "amount": "", "maturity": "", "rate": ""}],
  "covenants": "",
  "credit_facility": {"size": "", "drawn": ""},
  "off_balance_sheet_impact": "",
  "insufficient_data": false
}
```
