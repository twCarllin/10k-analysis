---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_financial_analysis

## Purpose
分析日本有価証券報告書 5 年財務 summary（由 TA3 `extract_five_year_summary` 抽出），解讀收入趨勢、獲利能力、資本結構與現金產生能力。

## Input
- `xbrl_data`（必填）：TA3 `extract_five_year_summary` 回傳的 dict，JSON 字串格式。包含 `five_year_summary`（各指標 5 年時間序列）、`accounting_standard`（JGAAP / IFRS / USGAAP）、`currency`、`unit_scale` 等 key。**非原始 XBRL，不含 decimals 屬性。**
- `prior_xbrl_data`（選填）：前一份有報的同格式 dict，用於確認數字一致性（cross-check 訂正）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 依 `accounting_standard` 自行調整解讀：JGAAP 使用「ordinary_income（経常利益）」作為核心獲利指標；IFRS 無経常利益，改用 `net_income`；US GAAP 同 IFRS 處理。欄位對應依 `xbrl_data` 中實際存在的 key 為準。
2. 收入趨勢（revenue_trend）：計算 5 年 net_sales 的 CAGR、各年度 YoY 成長率，以繁體中文描述方向與加速/減速態勢。
3. 獲利能力趨勢（profitability_trend）：分析 ordinary_income（或 IFRS 替代指標）/ net_income 的絕對值與隱含利潤率變化（若 five_year_summary 無毛利，以 ordinary_income/net_sales 代替）。
4. 資產負債品質（balance_sheet_quality）：分析 total_assets 成長、equity_ratio_pct 趨勢、net_assets 變化。
5. 現金產生能力（cash_generation）：分析 operating_cash_flow 的 5 年趨勢，說明現金轉換能力。
6. 報酬指標（return_metrics）：分析 roe_pct、eps_yen、bps_yen 的趨勢方向。
7. 異常值標記（anomalies）：任一指標單年 YoY 絕對變動 > 30%，標記說明（不說「惡化」，說「下降 X%」）。
8. 整體財務體質評估（overall_health）：綜合以上給出 strong / stable / weak，附一句佐證理由。
9. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "revenue_trend": {
    "cagr_5yr_pct": null,
    "yoy_pcts": [{"fiscal_year_end": "", "yoy_pct": null}],
    "summary": ""
  },
  "profitability_trend": {
    "margin_series": [{"fiscal_year_end": "", "margin_pct": null}],
    "summary": ""
  },
  "balance_sheet_quality": {
    "equity_ratio_trend": "",
    "summary": ""
  },
  "cash_generation": {
    "ocf_series": [{"fiscal_year_end": "", "val": null}],
    "summary": ""
  },
  "return_metrics": {
    "roe_trend": "",
    "eps_trend": "",
    "summary": ""
  },
  "anomalies": [
    {"fiscal_year_end": "", "metric": "", "note": ""}
  ],
  "overall_health": "strong|stable|weak",
  "overall_health_rationale": "",
  "insufficient_data": false
}
```
