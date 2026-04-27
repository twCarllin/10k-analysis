---
skill_version: 1.0
last_modified: 2025-04-23
---

# insight_synthesis

## Purpose
綜合所有分析結果，產出投資 insight：Bull/Bear case + Key monitorables。

## Input
- `analysis_results`（必填）：所有 agent 分析結果 JSON
- `comparator_result`（必填）：cross_year_compare 輸出 JSON
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. Bull case：最多 3 點，每點有具體數字或事件
2. Bear case：最多 3 點，同上
3. Key monitorables：未來 2 季需追蹤（3~5 點）
4. Information edge：散戶忽視但分析發現的訊號（優先來自 footnotes/governance quality_flags）
5. 整體信心評分（low_confidence_tasks 存在時自動降評）

## Output Format
```json
{
  "bull_case": [{"point": "", "evidence": ""}],
  "bear_case": [{"point": "", "evidence": ""}],
  "key_monitorables": [],
  "information_edge": [{"signal": "", "source": ""}],
  "confidence": "high|medium|low",
  "confidence_reason": "",
  "low_confidence_tasks": [],
  "insufficient_data": false
}
```
