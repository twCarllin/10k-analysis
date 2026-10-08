---
skill_version: 1.0
last_modified: 2026-05-01
---

# transcript_analysis

## Purpose
分析 earnings call transcript，萃取前瞻指引、市場關注議題、管理層情緒與策略布局，提供投資決策所需的可操作洞察。

## Input
- `transcript`（必填）：`Transcript` 物件的 JSON 字串，包含：
  - `ticker`：公司代碼（string）
  - `quarter`：季度，如 `"Q1"`（string）
  - `year`：年度，如 `"2026"`（string）
  - `participants`：參與者列表（name / role / affiliation）
  - `sections.prepared_remarks`：管理層準備好的發言 segments（含 speaker / text）
  - `sections.qa`：分析師問答環節 segments（含 speaker / text）
  - `raw_text`：全文純文字（僅作為補充參考，主分析來源是 sections）
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions

### 1. 結構化摘要 (Structured Summary)
從 transcript 中提取本季營運的關鍵事實，不帶主觀判斷。

- **業績概況**：revenue、EPS、margin 等關鍵指標的 beat/miss 情況，以及管理層歸因的驅動因子
- **各業務線表現**：按 segment/product line 拆解，標記 YoY/QoQ 變化方向；`segment_performance[].direction` 可接受值：`up | flat | down`
- **營運亮點與挑戰**：管理層主動強調的正面進展，以及坦承的 headwind
- **資本配置**：回購計畫、股利政策、capex 調整、M&A 意向

注意：只提取 transcript 中明確提到的資訊，不要推測或補充外部知識。

### 2. 市場關注議題 (Market Concerns)
識別分析師在 Q&A 中反覆追問的核心議題，反映市場最擔心的風險點。

**挑選方式**：
- 依議題在 Q&A 中被提問的頻率（多個分析師追問同一主題 = 高頻）排序
- 選取頻率最高的 **3-5 個議題**，不要把所有 Q&A 都列出
- 如果高頻議題不足 3 個，只列實際出現的數量

**各議題必須包含**：
- `topic`：議題摘要（繁體中文）
- `frequency`：被提問次數（整數，從 Q&A segments 計算）
- `management_response`：管理層的具體回應（繁體中文，≤ 100 字）
- `verbatim_response`：管理層原話一句以內（英文，sell-side 慣例保留英文原文）
- `evasion_signal`：明確迴避才填（例如：拒絕給出數字、反覆套用 boilerplate 措辭、直接轉移至其他話題）；一般性定性回應（如「我們持續觀察市場」）不算迴避，填 `null`；有迴避跡象時描述具體方式（繁體中文）

### 3. 情緒分析 (Sentiment Analysis)
分析管理層的語氣和信心程度，區分 prepared remarks 和 Q&A 的差異。

- **整體基調**：bullish / cautiously_optimistic / neutral / cautious / defensive
- **信心程度**：0.0（極度保守）到 1.0（極度樂觀）
- **Prepared vs Q&A 落差**：兩者語氣是否一致，不一致通常值得注意
- **CEO vs CFO 語氣**：對同一議題的措辭是否對齊
- **迴避訊號**：標記被迴避的問題（過長繞圈子、過短敷衍、轉移話題）
- **語言轉變**：與前季相比，對同一議題的措辭變化（若無前季資料則填空陣列）

### 4. 前瞻指引 (Forward Guidance)
提取所有關於未來的具體陳述，區分硬指引（有數字）和軟指引（定性描述）。

- **硬指引**：指標名稱 / 數值或範圍 / 適用期間 / 方向（raised/maintained/lowered/initiated/withdrawn） / 原文引用（英文原文）
- **軟指引**：涉及領域 / 方向描述 / 管理層信心程度（enum：`high | medium | low`，**非數字**；與 `sentiment.confidence_level` 的 0.0-1.0 浮點數不同）
- **指引變動**：與前季指引比較，標記任何上修、下修、或措辭轉變
- **隱含訊號**：管理層沒有直接給指引，但暗示方向的陳述

### 5. 重要合作案與策略布局 (Key Partnerships & Strategic Initiatives)
提取所有涉及外部合作、客戶關係、策略轉向的資訊。

- **新合作案/客戶**：新宣布的合作夥伴、客戶名單、design win
- **既有合作進展**：已知合作案的更新（擴大規模、延長合約、里程碑達成）
- **策略轉向**：進入新市場、退出業務線、組織重整、技術路線調整
- **競爭態勢**：管理層對競爭者的提及或暗示
- **供應鏈動態**：供應商關係、產能狀況、地緣政治影響

## Output Format

嚴格按照以下 JSON schema 輸出，不加說明文字、不加 markdown code block：

```json
{
  "ticker": "INTC",
  "quarter": "Q1",
  "year": "2026",
  "analysis_date": "2026-05-01T00:00:00Z",

  "structured_summary": {
    "headline": "一句話總結本季最重要的訊息（繁體中文）",
    "financial_highlights": [
      {
        "metric": "Revenue",
        "reported": "$12.7B",
        "consensus": "$12.3B",
        "beat_miss": "beat",
        "yoy_change": "+8%",
        "driver": "管理層歸因的原因（繁體中文）"
      }
    ],
    "segment_performance": [
      {
        "segment": "Client Computing Group",
        "direction": "up",
        "detail": "簡述表現（繁體中文）"
      }
    ],
    "operational_highlights": ["正面進展 1（繁體中文）"],
    "operational_challenges": ["挑戰 1（繁體中文）"],
    "capital_allocation": {
      "buyback": "回購計畫描述或 null（繁體中文）",
      "dividend": "股利政策或 null（繁體中文）",
      "capex": "capex 計畫或 null（繁體中文）",
      "ma": "M&A 意向或 null（繁體中文）"
    }
  },

  "market_concerns": [
    {
      "topic": "AI accelerator 出貨能否對抗 NVIDIA（繁體中文）",
      "frequency": 4,
      "management_response": "管理層具體回應（繁體中文，≤ 100 字）",
      "verbatim_response": "管理層原話一句以內（英文原文）",
      "evasion_signal": null
    }
  ],

  "sentiment": {
    "overall_tone": "cautiously_optimistic",
    "confidence_level": 0.65,
    "prepared_remarks_tone": "bullish",
    "qa_tone": "cautious",
    "tone_gap": "prepared remarks 偏樂觀但 Q&A 面對特定問題時有所保留（繁體中文）",
    "ceo_cfo_alignment": "aligned 或描述分歧點（繁體中文）",
    "evasive_topics": [
      {
        "topic": "被迴避的問題（繁體中文）",
        "signal": "回答過長/轉移話題/模糊帶過（繁體中文）"
      }
    ],
    "notable_language_shifts": [
      {
        "topic": "議題（繁體中文）",
        "previous": "前季用語（英文原文）",
        "current": "本季用語（英文原文）",
        "interpretation": "解讀（繁體中文）"
      }
    ]
  },

  "forward_guidance": {
    "hard_guidance": [
      {
        "metric": "Q2 Revenue",
        "value": "$12.5B - $13.5B",
        "period": "Q2 2026",
        "direction": "raised",
        "verbatim": "管理層原話（英文原文）"
      }
    ],
    "soft_guidance": [
      {
        "area": "涉及領域（繁體中文）",
        "direction": "positive",
        "detail": "定性描述（繁體中文）",
        "confidence": "high"
      }
    ],
    "guidance_changes": [
      {
        "metric": "指標名稱（英文）",
        "previous": "前季指引",
        "current": "本季指引",
        "change": "raised"
      }
    ],
    "implied_signals": ["隱含訊號（繁體中文）"]
  },

  "partnerships_and_strategy": {
    "new_partnerships": [
      {
        "partner": "合作方名稱（英文）",
        "nature": "customer",
        "detail": "描述（繁體中文）",
        "scale": "規模或 null",
        "revenue_impact": "潛在營收影響評估（繁體中文）或 null"
      }
    ],
    "existing_updates": [
      {
        "partner": "合作方（英文）",
        "status": "expanding",
        "detail": "更新內容（繁體中文）"
      }
    ],
    "strategic_shifts": [
      {
        "area": "領域（繁體中文）",
        "description": "描述（繁體中文）",
        "implications": "對投資人的意義（繁體中文）"
      }
    ],
    "competitive_dynamics": ["競爭態勢觀察（繁體中文）"],
    "supply_chain": ["供應鏈動態（繁體中文）"]
  },

  "insufficient_data": false
}
```

## Tone Guidelines
- 使用事實描述語氣，不使用評價性語氣
- 避免：惡化、崩潰、警訊、危機、大幅、顯著
- 改用：下降、收窄、減少、增加、變化
- 數字優先：不說「毛利明顯惡化」，說「毛利率從 42% 降至 38%」
- 不確定的事用條件句：「若趨勢持續，可能影響...」
- 正負面訊號用相同的語氣強度呈現，不放大任何一方

## 語言規則
分析內容使用繁體中文。以下欄位保留英文原文不翻譯：
- `verbatim` / `verbatim_response`：管理層原話必須保留英文
- `notable_language_shifts` 的 `previous` / `current`：用語對比需要看原文
- `partner`：公司/機構名稱保留英文
- `metric`、`segment`：財務指標和業務線名稱保留英文
- enum 值（`tone`、`direction`、`status`、`nature`、`confidence` 等）：維持英文 enum

## 分析原則
1. **事實優先**：只基於 transcript 內容分析，不要補充外部知識或假設
2. **引用原文**：關鍵判斷必須附上 transcript 中的原話作為依據（一句以內）
3. **標記不確定性**：如果資訊模糊或不確定，用 `"unclear"` 或 `"insufficient_data": true` 標記，不要猜
4. **區分事實與解讀**：`detail` 欄位放事實，`interpretation` 或 `implications` 放分析
5. **空值處理**：如果某個欄位在 transcript 中找不到對應資訊，設為 `null` 或空陣列，不要硬湊
6. **market_concerns 數量**：挑頻率最高的 3-5 個議題；若高頻議題不足 3 個，只列實際出現的數量，不要填充低頻議題
