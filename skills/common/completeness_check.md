---
skill_version: 1.0
last_modified: 2025-04-23
---

# completeness_check

## Purpose
驗證整份報告的覆蓋完整性，在輸出前做最後品質把關。
不重新分析，只評估已有輸出是否足夠讓投資者做判斷。

## Input
- all_results（必填）：所有 agent 輸出的完整 JSON
- eval_summary（必填）：eval_runner 的分數摘要 JSON
- retry_hint（選填）

## Instructions
評估六個維度的覆蓋完整性，各 0~10 分：

### 1. Business Coverage（0~10）
- 10：業務結構、競爭優勢、成長驅動都有實質內容，segment 完整
- 5：有覆蓋但部分 segment 缺失或描述過於簡略
- 0：major segment 完全未覆蓋，或 insufficient_data = true

### 2. Risk Coverage（0~10）
- 10：有跨年 delta，前 3 大風險有具體說明與措辭強度分析
- 5：有風險列表但缺乏 delta，或未說明優先順序
- 0：risk section 缺失或 insufficient_data = true

### 3. Financial Coverage（0~10）
- 10：Revenue / Margin / FCF / CapEx 四個維度都有趨勢分析，有 quality_flags
- 5：主要指標有但缺 FCF 或 quality_flags 為空
- 0：財務分析缺失或 metrics 為空

### 4. Quality Signal Coverage（0~10）
- 10：footnotes 有分析，unusual_operations 有結果（空陣列也算，代表已掃描）
- 5：只有其中一個有實質內容
- 0：兩個都缺失或 insufficient_data = true

### 5. Forward-Looking Coverage（0~10）
- 10：key monitorables 有 3+ 個可追蹤指標，有跨年 delta，有 mgmt credibility
- 5：有部分但不完整
- 0：缺乏任何前瞻性分析

### 6. Internal Consistency（0~10）
- 10：各 agent 結論相互印證，cross_checks 識別矛盾並已解釋
- 5：有輕微矛盾，部分已在 cross_checks 標記
- 0：明顯矛盾未被識別

識別 Critical Gaps：
- 任何維度覆蓋明顯不足 → critical gap，必須列出具體 issue 和 remedy
- 10-Q 季報天生缺少 Business / Risk Factors 章節，不應因此標記為 critical gap

## Output Format
```json
{
  "critical_gaps": [
    {
      "dimension": "",
      "issue": "",
      "remedy": ""
    }
  ],
  "low_confidence_task_count": 0,
  "summary": "一句話總結報告品質與主要缺口",
  "insufficient_data": false
}
```
