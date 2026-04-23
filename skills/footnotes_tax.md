---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_tax

## Purpose
分析 Note H (Income Taxes)，聚焦稅務結構、遞延稅資產與不確��稅務部位。

## Input
- `current_section`（必填）：Note H 全文
- `retry_hint`（選填）

## Instructions
1. 有效稅率 vs 法定稅率，主要調節項目
2. 遞延稅資產/負債組成，評價備抵金額與變動
3. 不確定稅務部位（UTP）金額與變動
4. 海外未匯回盈餘與潛在稅務影響
5. 稅務爭議或審查狀況
6. R&D 稅務抵減或其他重大抵減項目

## Output Format
```json
{
  "effective_rate": "",
  "statutory_vs_effective": "",
  "major_adjustments": [],
  "deferred_tax": {"assets": "", "liabilities": "", "valuation_allowance": "", "va_change": ""},
  "uncertain_tax_positions": {"amount": "", "change": ""},
  "tax_disputes": [],
  "tax_credits": [],
  "insufficient_data": false
}
```
