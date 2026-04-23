---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_compensation

## Purpose
分析 Note I (Stock & SBC) + Note J (EPS) + Note K (AOCI)，聚焦股權薪酬稀釋與綜合損益。

## Input
- `current_section`（必填）：Note I + J + K 全文
- `retry_hint`（選填）

## Instructions
1. 股權薪酬費用金額與佔營收比
2. 未歸屬獎勵的未認列費用與加權平均歸屬期間
3. 庫藏股回購金額與股數
4. 基本 vs 稀釋 EPS，稀釋來源
5. AOCI 各組成項目（退休金、外幣、避險）及變動

## Output Format
```json
{
  "sbc": {"expense": "", "to_revenue_pct": "", "unrecognized": "", "vest_period": ""},
  "buyback": {"shares": "", "amount": ""},
  "eps": {"basic": "", "diluted": "", "dilution_sources": ""},
  "aoci_components": [{"item": "", "amount": "", "change": ""}],
  "insufficient_data": false
}
```
