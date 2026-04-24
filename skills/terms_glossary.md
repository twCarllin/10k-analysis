---
skill_version: 1.0
last_modified: 2025-04-23
---

# terms_glossary

## Purpose
掃描 SEC 申報文件全文，找出需要解釋的術語，產出報告附錄用的 glossary。
讓非專業讀者能讀懂報告，也幫助其他 agent 建立共同語彙。

## Input
- all_sections_md（必填）：item1 + item1a + item7 + item8 footnotes 前段合併文字
- retry_hint（選填）

## Instructions
找出以下四類術語，每類都要找，不能遺漏：

### 1. 財務術語（category: financial）
GAAP/非 GAAP 指標、會計處理名詞。
例：攤銷（Amortization）、商譽減損（Goodwill Impairment）、
    應收帳款證券化（AR Securitization）、遞延收入（Deferred Revenue）

### 2. 行業術語（category: industry）
該產業特有的黑話，外行人看不懂的縮寫。
例（航太製造）：MRO（Maintenance Repair & Overhaul）、
    OEM（Original Equipment Manufacturer）、
    book-to-bill ratio、aftermarket

### 3. 公司自定義指標（category: company_defined）
管理層自創的 KPI 或 segment 名稱，在財報以外看不到標準定義。
例：公司自定義的 "Adjusted EBITDA"、segment 名稱如 "Engine Products"

### 4. 法律/監管術語（category: regulatory）
SEC 規定、合規名詞、法律條款。
例：Material Weakness、Going Concern、Safe Harbor Statement

對每個術語提供：
- term：原文術語（英文或中文）
- category：financial / industry / company_defined / regulatory
- explanation：50 字以內的白話解釋，避免用其他術語解釋術語
- importance：high（影響投資判斷）/ medium（輔助理解）/ low（純背景知識）

## Output Format
```json
{
  "terms": [
    {
      "term": "AR Securitization",
      "category": "financial",
      "explanation": "公司將應收帳款打包出售給特殊目的機構換取現金，帳款移出資產負債表，實際槓桿比報表顯示的高",
      "importance": "high"
    }
  ],
  "high_importance_count": 0,
  "category_counts": {
    "financial": 0,
    "industry": 0,
    "company_defined": 0,
    "regulatory": 0
  },
  "insufficient_data": false
}
```
