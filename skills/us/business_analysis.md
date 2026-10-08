---
skill_version: 1.0
last_modified: 2025-04-23
---

# business_analysis

## Purpose
分析 SEC 申報文件 Business 章節（10-K Item 1），萃取業務結構、收入來源與競爭優勢。

## Input
- `current_section`（必填）：當年 Item 1 全文
- `prior_section`（選填）：前一年 Item 1 全文
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 公司自我定位：公司如何描述自己？核心價值主張是什麼？在產業鏈中扮演什麼角色？用 2-3 句繁體中文摘要公司的自我敘事。關鍵專有名詞可保留英文，但整體敘述以中文為主，不要大段引用英文原文
2. 成長敘事：公司認為未來成長的主要驅動力是什麼？用繁體中文撰寫，特別注意：
   - 終端市場需求變化（如 AI/資料中心帶動電力需求、航太復甦、能源轉型等）
   - 市場分類的重新定義（新增或合併市場類別往往反映策略重心轉移）
   - 成長相關的具體數字與趨勢方向
3. 主要業務部門與收入來源（依重要性排序），標註各終端市場佔比
4. 客戶集中度與地理分布
5. 核心競爭優勢措辭加強或弱化（引用原文）
6. 有 prior_section 時：新/退出業務線、市場分類變動、策略重心轉移

## Output Format
```json
{
  "company_positioning": "",
  "growth_narrative": "",
  "business_segments": [{"name": "", "description": "", "revenue_weight": "high|medium|low"}],
  "end_market_mix": [{"market": "", "pct": "", "trend": "growing|stable|declining"}],
  "revenue_drivers": [],
  "customer_concentration": "",
  "geographic_mix": [],
  "competitive_moat_delta": "",
  "new_or_exited": [],
  "insufficient_data": false
}
```
