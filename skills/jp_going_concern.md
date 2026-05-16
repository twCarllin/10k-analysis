---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_going_concern

## Purpose
分析日本有価証券報告書「継続企業の前提に関する事項」章節（jpcrp_cor:MattersRelatedToGoingConcernAssumptionTextBlock），判斷持續經營疑義的嚴重程度與管理層因應計畫。

## Input
- `current_section`（必填）：當年繼続企業章節日文原文（TA4 `split_filing_by_ixbrl` 的 `going_concern` key）。若該公司無 going concern 揭露，此 key 在 split 結果中不存在，caller 應傳入空字串 `""` 或 `"<placeholder>"`。
- `prior_section`（選填）：前一年同章節日文原文
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. **空 input 處理**：若 `current_section` 為空字串、僅含空白、或值為 `"<placeholder>"`，直接回傳：
   ```json
   {
     "insufficient_data": true,
     "has_disclosure": false,
     "concern_level": "none",
     "triggers": [],
     "remediation_plan": null,
     "commitment_strength": null
   }
   ```
   不做任何推論，不補充外部知識。
2. 若 input 非空：判斷揭露是否為實質性疑義（has_disclosure = true）。
3. 疑義嚴重程度（concern_level）：
   - `"none"` — 無疑義或僅例行性聲明
   - `"light"` — 提及潛在疑慮但管理層評估無重大疑義
   - `"material"` — 有重大疑義，已揭露且列入財報附註
   - `"severe"` — 獨立審計師出具意見，或管理層明確認定持續經營有重大不確定性
4. 觸發因素（triggers）：列出管理層提及的具體財務或營運因素（如連續虧損、債務違約、流動比率不足等）。
5. 因應計畫（remediation_plan）：管理層說明的具體對策（如增資、資產出售、取得授信額度等）。
6. 承諾強度（commitment_strength）：依管理層對因應計畫的措辭強度判斷（high/medium/low/null），參考 jp_mdna_analysis 的敬語層次規則。
7. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "has_disclosure": false,
  "concern_level": "none|light|material|severe",
  "triggers": [],
  "remediation_plan": "",
  "commitment_strength": "high|medium|low|null",
  "insufficient_data": false
}
```
