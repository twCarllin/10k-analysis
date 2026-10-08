---
skill_version: 1.0
last_modified: 2025-04-23
---

# financial_analysis

## Purpose
三層 input 財務分析，在自身 context 內做初步交叉驗證。

## Input
- `xbrl_json`（必填）：XBRL 結構化數字（extract_key_metrics 輸出）
- `fs_md`（選填）：Item 8 三張報表 Markdown，提供脈絡
- `footnotes_summary`（選填）：footnotes_agent 的 JSON 輸出，用於交叉驗證
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 各指標年度趨勢與 YoY 成長率（最近 3~5 年）
2. 毛利率、營業利益率、FCF conversion（FCF/Net Income）
3. 資本配置優先序（CapEx/Buyback/Dividend）
4. 異常值標記（單年突變 > 20%）
5. 若有 footnotes_summary，執行交叉驗證填入 quality_flags：
   - revenue_recognition.changed = true → "revenue 數字可信度降低"
   - contingencies high likelihood → "潛在 liability 未入帳"
   - sbc_to_revenue > 10% → "dilution 壓力高"
   - off_balance_sheet 重大項目 → "槓桿被低估"
6. 若有 fs_md，對照確認 XBRL 數字無明顯異常
7. 季度趨勢解讀：若 xbrl_json 包含季度數據，分析最近幾季的營收成長率、營業利益率、淨利率趨勢方向（加速/減速/穩定），識別轉折點

## Output Format
```json
{
  "metrics": {
    "Revenue":             [{"year": 0, "val": 0, "yoy_pct": null}],
    "GrossMargin_pct":     [{"year": 0, "val": 0}],
    "OperatingMargin_pct": [{"year": 0, "val": 0}],
    "FCF_conversion":      [{"year": 0, "val": 0}],
    "CapEx_to_Revenue":    [{"year": 0, "val": 0}]
  },
  "capital_allocation_order": [],
  "anomalies": [{"year": 0, "metric": "", "note": ""}],
  "quality_flags": [],
  "trend_summary": "",
  "insufficient_data": false
}
```
