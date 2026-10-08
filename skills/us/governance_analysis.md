---
skill_version: 1.0
last_modified: 2025-04-23
---

# governance_analysis

## Purpose
分析 10-K Part III（Item 9A + 10 + 11 + 13）章節，萃取治理結構、審計意見與薪酬對齊。
（僅適用於 10-K 年報，10-Q 季報不含此章節。）

## Input
- `current_section`（必填）：Item 9A + 10 + 11 + 13 合併文字
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 審計師意見類型
2. Internal control 缺陷
3. 高管薪酬結構與 KPI 對齊
4. 大股東持股（>5%）與近期變動
5. 董事會獨立性
6. Item 13 關聯交易（補充 footnotes_analysis）

## Output Format
```json
{
  "audit_opinion": "unqualified|qualified|adverse|disclaimer",
  "internal_control_issues": [],
  "exec_compensation": {"structure": "", "performance_linked_pct": "", "kpi_alignment": "aligned|misaligned|unclear"},
  "major_shareholders": [{"name": "", "pct": "", "change": ""}],
  "board_independence_pct": "",
  "related_party_item13": [],
  "governance_flags": [],
  "insufficient_data": false
}
```
