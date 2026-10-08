---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_risk

## Purpose
分析 Note U (Contingencies & Commitments) + Note V (Subsequent Events) + Note P (Leases)，聚焦或有負債與表外承諾。

## Input
- `current_section`（必填）：Note U + V + P 全文
- `retry_hint`（選填）

## Instructions
1. 或有負債：各項訴訟/爭議的金額、可能性（probable/reasonably possible/remote）
2. 環境修復義務金額與涉及地點數量
3. 承諾事項：採購承諾、擔保、賠償義務
4. 租賃負債：營運租賃 vs 融資租賃、未來支付時程
5. 後續事件：是否影響財報數字或需揭露

## Output Format
```json
{
  "contingencies": [{"description": "", "amount": "", "likelihood": "probable|reasonably_possible|remote"}],
  "environmental": {"reserve": "", "sites_count": "", "current_portion": ""},
  "commitments": [{"type": "", "amount": "", "nature": ""}],
  "leases": {"operating_total": "", "finance_total": ""},
  "subsequent_events": [],
  "insufficient_data": false
}
```
