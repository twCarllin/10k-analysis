---
skill_version: 1.0
last_modified: 2026-04-28
---

# supply_chain_analysis

## Purpose
從 10-K / 10-Q 多個 section 系統性萃取供應鏈資訊，
評估供應鏈集中風險、地緣政治暴露、原物料依賴，
並追蹤跨年的供應鏈結構改善或惡化。

核心投資邏輯：
供應鏈結構的改善（多元化、在地化、長約鎖定）是潛在的正面投資因素。
供應鏈惡化（單一來源增加、原物料價格上升、地緣風險加重）是警訊。

適用所有產業，skill 會根據文件內容自動識別：
- 製造業：原物料、特殊金屬、零組件供應商
- 科技業：晶片、設備、稀有氣體、軟體授權
- 零售業：亞洲製造集中、物流、港口依賴
- 能源業：鑽探設備、管材、地緣政治
- 醫療器材：FDA 核准供應商限制、電子元件

## Input
- `item1_current`（必填）：當期 Item 1 Business 全文（10-Q 時傳入空字串）
- `item1a_current`（必填）：當期 Item 1A Risk Factors 全文
- `item7_current`（必填）：當期 Item 7 MD&A 全文
- `item8_footnotes_current`（選填）：當期 Item 8 Footnotes 全文
- `item1_prior`（選填）：前一期 Item 1（做跨年比較）
- `item1a_prior`（選填）：前一期 Item 1A（做跨年比較）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions

### Step 1：從 Item 1 Business 找供應鏈結構
搜尋以下段落標題與關鍵字：
  Suppliers, Raw Materials, Sources of Supply,
  Procurement, Single-source, Sole-source

抽出：
1. 主要原物料清單（名稱、用途）
2. 有無點名具體供應商（直接引用原文）
3. 是否有 single-source 或 sole-source 風險揭露
4. 有無提及替代供應商開發計畫

若 `item1_current` 為空字串（10-Q 路徑），此 Step 略過，僅從 Step 2-4 萃取。

### Step 2：從 Item 1A Risk Factors 找供應鏈風險
搜尋以下關鍵字：
  supply chain, supplier, raw material, single source,
  geopolitical, tariff, trade restriction, shortage,
  rare earth, titanium, nickel, aluminum, semiconductor

對每個識別到的供應鏈風險：
- 摘要風險內容（50 字以內）
- 分類：
    concentration（供應商集中）
    geopolitical（地緣政治）
    price（原物料價格）
    shortage（供應短缺）
    logistics（物流/運輸）
    regulatory（法規/關稅）
- 若有 `item1a_prior`：對比前一年措辭，標記 new / escalated / stable / resolved
- 若無 `item1a_prior`：yoy_status 設為 `"stable"`

### Step 3：從 Item 7 MD&A 找實際影響
搜尋：
  supply chain, supplier, raw material, inflation,
  cost headwind, price increase, availability

抽出：
- 供應鏈問題對當期財務的實際影響（引用金額或比率）
- 管理層對供應鏈前景的描述
- 有無提及採購成本上升或下降

### Step 4：從 Item 8 Footnotes 找採購承諾（選填）
若 `item8_footnotes_current` 有傳入，搜尋：
  purchase commitment, take-or-pay, long-term supply,
  minimum purchase, supply agreement

抽出：
- 長期採購合約的承諾金額與期限
- Take-or-pay 合約的條款摘要
- 這些承諾的財務規模佔 Revenue 的比率（若可計算）

若 `item8_footnotes_current` 為空，`purchase_commitments.found` 設為 false。

### Step 5：跨年比較（若有 prior sections）
比對前一年的供應鏈揭露，找出：

改善訊號（Bullish）：
- 新增第二供應商 / 替代來源
- 長期合約鎖定價格
- 在地化採購比例提升
- 特定地緣風險的替代方案落地

惡化訊號（Bearish）：
- 新增 single-source 依賴
- 地緣政治風險揭露升級（"may" → "has"）
- 採購合約承諾金額大幅增加（被迫鎖定高價）
- 原物料短缺從 Risk Factor 出現在 MD&A（已實際發生）

若無 prior sections，`yoy_changes.improvements` 與 `yoy_changes.deteriorations` 均設為空 list。

### Step 6：評估投資影響
綜合以上分析，給出：
- `overall_risk_level`：high / medium / low（綜合集中度、地緣暴露、財務影響）
- `trend`：improving / stable / deteriorating（與前一年相比的整體方向）
- `rerating_relevance`：positive / negative / neutral（供應鏈變化是否影響投資判斷，為 skill 自身評估，非與其他 skill 串接的輸入）
- `rerating_note`：說明供應鏈變化對投資判斷的具體影響，引用文件中的改善或惡化證據

## Output Format
```json
{
  "raw_materials": [
    {
      "material": "原物料名稱（如 Titanium alloy / NAND flash / Cotton）",
      "usage": "用途描述",
      "source_concentration": "high|medium|low",
      "geographic_risk": "高風險地區 or diversified",
      "notes": ""
    }
  ],
  "named_suppliers": [
    {
      "name": "供應商名稱（若有點名）",
      "material_or_service": "",
      "single_source": true,
      "yoy_status": "new|existing|removed"
    }
  ],
  "supply_chain_risks": [
    {
      "title": "",
      "summary": "",
      "category": "concentration|geopolitical|price|shortage|logistics|regulatory",
      "yoy_status": "new|escalated|stable|resolved",
      "mdna_realized": false
    }
  ],
  "mdna_impact": {
    "financial_impact_mentioned": true,
    "impact_description": "Supply chain inflation increased COGS by approximately $XX million",
    "mgmt_outlook": "conservative|neutral|optimistic"
  },
  "purchase_commitments": {
    "found": true,
    "total_commitment_description": "",
    "take_or_pay_noted": false,
    "commitment_to_revenue_pct": ""
  },
  "yoy_changes": {
    "improvements": ["具體改善描述，引用文件原文或數字"],
    "deteriorations": ["具體惡化描述，引用文件原文或數字"]
  },
  "overall_risk_level": "high|medium|low",
  "trend": "improving|stable|deteriorating",
  "rerating_relevance": "positive|negative|neutral",
  "rerating_note": "說明供應鏈變化對投資判斷的具體影響，引用文件中的改善或惡化證據",
  "insufficient_data": false
}
```

---

_skill_note: 本 skill 為獨立模組，輸出不影響其他 skill 的判斷邏輯，僅在 report_writer Supply Chain Analysis 段落呈現。supply_chain_analysis 結果不傳入任何其他 skill，亦不參與整體投資評級的 verdict 計算。
