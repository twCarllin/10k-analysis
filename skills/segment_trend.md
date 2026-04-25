---
skill_version: 1.0
last_modified: 2025-04-23
---

# segment_trend

## Purpose
分析公司各業務部門（Segment）的多年營收佔比變化，
識別「結構轉型」訊號：哪個業務在崛起、哪個在萎縮。

核心原則：只看單年數字毫無意義，只有跨年「變化」才是分析的起點。

## Input
- xbrl_json（必填）：extract_key_metrics() 的 JSON 字串
- business_summary（必填）：business_agent 輸出的 JSON 字串
  （包含 segment 名稱與業務描述）
- mdna_summary（選填）：mdna_agent 輸出的 JSON 字串
  （用來驗證 segment 變化是否和管理層敘述一致）
- retry_hint（選填）

## Instructions

### Step 1：建立 Segment 四年趨勢表
從 business_summary 取得各 segment 名稱，
對應 XBRL 數據計算每個 segment 的年度營收佔比（%）。
至少拉 2 年，能拉 3 年更好。

格式範例：
  Segment    | Y-3  | Y-2  | Y-1  | Y0
  Hardware   | 70%  | 60%  | 48%  | 38%
  SaaS       | 20%  | 28%  | 35%  | 42%
  AI         |  5%  | 10%  | 15%  | 18%

### Step 2：識別結構性轉變
判斷標準（任一成立即標記）：
- 任一 segment 佔比 2 年內變化超過 15 個百分點
- 最高毛利 segment 佔比持續上升（品質改善）
- 最低毛利 segment 佔比持續下降（去低利化）
- 新 segment 出現（公司在佈局新業務）

結構轉變分類：
- upgrading：往高毛利、高可見度業務轉型（SaaS / 訂閱 / AI）
- downgrading：往低利或周期性業務轉型
- stable：各 segment 佔比變化 < 5%，無明顯轉型
- diversifying：新增業務線，整體分散化

### Step 3：與 MD&A 敘事交叉驗證（若有 mdna_summary）
管理層說的轉型方向，和 segment 數字是否一致？

一致：敘事有數字支撐，可信度高
不一致：管理層在說轉型，但數字還看不到 → 早期投資 or 口號

### Step 4：與 MD&A 敘事交叉驗證結果摘要

將 Step 3 的一致性結論寫入 mdna_consistency 欄位。

## Output Format
```json
{
  "segment_table": [
    {
      "segment": "SaaS",
      "revenue_pct": {"Y-3": 20, "Y-2": 28, "Y-1": 35, "Y0": 42},
      "direction": "rising|falling|stable",
      "margin_quality": "high|medium|low"
    }
  ],
  "shift_description": "公司正在去硬體化，SaaS + AI 合計佔比從 25% 升至 60%",
  "mdna_consistency": "consistent|inconsistent|no_prior_data",
  "mdna_consistency_note": "",
  "watch_segments": ["需要持續追蹤的 segment 名稱"],
  "insufficient_data": false
}
```
