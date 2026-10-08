---
skill_version: 1.0
last_modified: 2026-10-08
---

# tw_footnotes_quality

## Purpose
分析台灣上市櫃公司財報附註與年報風險事項中，與品質相關的揭露：關係人交易、或有事項、背書保證／資金貸與、關鍵查核事項。

## Input
- `fs_note_related`（選填）：關係人交易附註
- `fs_note_contingent`（選填）：或有事項與承諾附註
- `fs_note_disclosure`（選填）：背書保證、資金貸與、衍生品等揭露附註
- `fs_audit_kam`（選填）：關鍵查核事項
- `ar_risk`（選填）：年報風險事項節
- 以上至少一個非空。
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 關係人交易（related_party）：對象、性質、金額、佔比、條件是否異於常規；異於常規或佔比顯著者 flag 為 `watch`，否則 `normal`。
2. 或有事項與承諾（contingencies）：逐項說明。
3. 背書保證、資金貸與、衍生品（guarantees_and_loans）：以文字描述；無揭露時 flag 為 `none_disclosed`。
4. 關鍵查核事項（kam）：列出事項與其指向的風險。
5. 年報風險事項節中「高風險投資、資金貸與、背書保證」段落一併納入判讀。
6. 不做算術；輸入未提供的欄位不得臆測。
7. JSON value 一律使用繁體中文；語氣依 `agents/analyst_agent.md`。

## Output Format
```json
{
  "related_party": [{"counterparty": "", "nature": "", "amount_note": "", "flag": "normal|watch"}],
  "contingencies": [{"item": "", "note": ""}],
  "guarantees_and_loans": {"summary": "", "flag": "normal|watch|none_disclosed"},
  "kam": [{"matter": "", "risk_pointed": ""}],
  "key_observations": [""],
  "insufficient_data": false
}
```
