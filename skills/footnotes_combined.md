---
skill_version: 1.0
last_modified: 2026-04-24
---

# footnotes_combined

## Purpose
10-Q 合併附註分析：直接餵入完整附註文字，一次提取所有關鍵財務附註資訊，涵蓋收入認列、分部、負債、商譽/存貨、或有負債/租賃/後續事項、股份基礎薪酬/EPS、稅務等 7 大主題。

## Input
- `current_section`（必填）：完整財務報表附註文字（10-Q Item 1 Footnotes 全文）
- `retry_hint`（選填）

## Instructions
**重要：所有欄位必填，無資料填 null 或空字串，不可省略任何 key。**

1. **Revenue Recognition（收入認列）**：認列時點（point-in-time vs over-time vs mixed）、履約義務、variable consideration 處理；有無政策變動；新採用或即將採用的會計準則（ASU/FASB）及其預期影響。

2. **Segments & Restructuring（分部與重組）**：各報告分部名稱、分部營收、分部損益、資產佔比；有無分部重新定義；地理區域組合；重組費用總金額與性質。

3. **Debt & Credit Facility（負債與信貸設施）**：各類負債（senior notes、term loan、revolving credit 等）的金額、到期日、利率；信貸額度規模與已動用金額。

4. **Goodwill & Inventory（商譽與存貨）**：商譽總額、減損測試折現率/成長率/緩衝空間、累計減損；存貨計價方法（FIFO/LIFO）、LIFO 準備金。

5. **Contingencies, Leases & Subsequent Events（或有負債、租賃、後續事項）**：重大訴訟或有負債描述、金額、可能性評估（probable/reasonably_possible/remote）；營業租賃與融資租賃未來最低租金總額；資產負債表日後重大事項。

6. **SBC & EPS（股份基礎薪酬與每股盈餘）**：SBC 費用金額、佔營收比率、未認列補償費用、預計攤銷期間；基本 EPS、稀釋 EPS、稀釋效果來源（options/RSU/convertible 等）。

7. **Tax（稅務）**：有效稅率；遞延所得稅資產/負債總額；評價準備金；不確定稅務立場金額與期間變動。

## Output Format
```json
{
  "revenue_recognition": {
    "policy": "",
    "timing": "point-in-time|over-time|mixed",
    "changed": false,
    "change_detail": ""
  },
  "new_standards": [{"standard": "", "effective_date": "", "impact": ""}],
  "segments": [{"name": "", "revenue": "", "profit": "", "asset_pct": ""}],
  "segment_redefined": false,
  "geographic_mix": [],
  "restructuring": {"total_charge": "", "nature": ""},
  "debt_structure": [{"type": "", "amount": "", "maturity": "", "rate": ""}],
  "credit_facility": {"size": "", "drawn": ""},
  "goodwill": {
    "total": "",
    "impairment_test": {"discount_rate": "", "growth_rate": "", "cushion": ""},
    "cumulative_impairment": ""
  },
  "inventory": {"method": "", "lifo_reserve": ""},
  "contingencies": [{"description": "", "amount": "", "likelihood": "probable|reasonably_possible|remote"}],
  "leases": {"operating_total": "", "finance_total": ""},
  "subsequent_events": [],
  "sbc": {"expense": "", "to_revenue_pct": "", "unrecognized": "", "vest_period": ""},
  "eps": {"basic": "", "diluted": "", "dilution_sources": ""},
  "effective_rate": "",
  "deferred_tax": {"assets": "", "liabilities": "", "valuation_allowance": ""},
  "uncertain_tax_positions": {"amount": "", "change": ""},
  "insufficient_data": false
}
```
