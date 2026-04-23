---
skill_version: 1.0
last_modified: 2025-04-23
---

# footnotes_segment

## Purpose
分析 Note C (Segment Information) + Note D (Restructuring)，聚焦部門結構與重組活動。

## Input
- `current_section`（必填）：Note C + D 全文
- `retry_hint`（選填）

## Instructions
1. 報導部門數量與名稱，有無重新定義
2. 各部門營收、利潤、資產佔比
3. 地理區域分布與 major customer 揭露
4. 重組費用金額、性質、預期完成時間
5. 重組對各部門影響

## Output Format
```json
{
  "segments": [{"name": "", "revenue": "", "profit": "", "asset_pct": ""}],
  "segment_redefined": false,
  "geographic_mix": [],
  "major_customers": [],
  "restructuring": {"total_charge": "", "nature": "", "expected_completion": ""},
  "insufficient_data": false
}
```
