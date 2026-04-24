---
skill_version: 1.0
last_modified: 2025-04-23
---

# unusual_operations

## Purpose
識別 SEC 申報文件中不尋常的業務操作或會計處理，判斷是行業常態還是公司特殊操作，
說明對財務報表的影響與投資者應如何解讀。

## Input
- footnotes_summary（必填）：footnotes_agent 輸出的 JSON 字串
- financial_summary（必填）：financial_agent 輸出的 JSON 字串
- item8_footnotes_md（必填）：Item 8 footnotes 原文前 8000 字
- business_summary（選填）：business_agent 輸出的 JSON 字串（提供行業背景）
- retry_hint（選填）

## Instructions

### Step 1：建立候選清單
從以下來源識別候選項目，不要遺漏：

從 footnotes_summary 找：
- red_flags 中每一項
- off_balance_sheet 有金額的項目
- related_party 金額重大的項目
- revenue_recognition.changed = true

從 financial_summary 找：
- quality_flags 中每一項
- anomalies 中單年突變項目

### Step 2：在 item8_footnotes_md 原文搜尋細節
對每個候選項目，在原文中搜尋以下關鍵字找到具體描述：
securitization, factoring, sale-leaseback, synthetic lease,
special purpose, variable interest entity, off-balance,
non-GAAP, adjusted, excluding, accelerated, deferred,
channel stuffing, bill-and-hold

引用原文中的具體數字（金額、比率、日期）。

### Step 3：對每個識別項目判斷並說明
a. 描述操作內容（引用原文數字）
b. 分類：
   - industry_norm：該行業普遍做法，不具特殊性
   - company_specific：公司特有，其他公司少見
   - hybrid：行業常見但規模/方式有公司特殊之處
c. 分類依據（一句話說明為何如此分類）
d. 財務影響：對哪個報表科目有多少影響
e. 投資者解讀：
   - positive：操作對投資者有利
   - neutral：中性，了解即可
   - negative：需要警覺，可能低估風險

如果沒有識別到任何不尋常操作，unusual_items 輸出空陣列，這是合法結果。

## Output Format
```json
{
  "unusual_items": [
    {
      "name": "應收帳款證券化",
      "description": "HWM 將應收帳款出售給 SPE，2024 年規模約 $XXX million",
      "source_quote": "原文引用（盡量包含數字）",
      "classification": "industry_norm|company_specific|hybrid",
      "classification_rationale": "航太製造業普遍採用，用於優化營運資金",
      "financial_impact": "應收帳款低估，實際 leverage 比報表高約 X%",
      "investor_interpretation": "positive|neutral|negative",
      "investor_note": "計算 debt/EBITDA 時需將 off-balance sheet 金額加回"
    }
  ],
  "summary": "共識別 N 個不尋常操作，X 個屬行業常態，Y 個屬公司特殊，主要關注：...",
  "insufficient_data": false
}
```
