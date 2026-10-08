---
skill_version: 1.0
last_modified: 2025-04-25
---

# rerate_narrative

## Purpose
判斷管理層敘事是否正在從計畫階段轉向成果階段。

## Input
- mdna_summary（必填）：mdna_agent 輸出的 JSON 字串
- retry_hint（選填）

## Instructions

根據 mdna_summary.narrative_shift 的事實數據，判斷敘事是否在轉變。

判斷分兩層：

**第一層（主判斷）：敘事是否已成熟**
1. 計算 narrative_shift.mature_stage_language 的條目數（M）
2. M >= 3 → result = true
3. M < 3 → result = false
4. 若 mdna_summary 無 narrative_shift 欄位 → false

**第二層（僅當第一層為 false 時）：敘事是否正在成長**
1. 讀取 narrative_shift.momentum.direction
2. direction == "accelerating" → emerging = true
3. direction 為 null、不存在、或非 "accelerating" → emerging = false

注意：第一層判斷只看 M 的數量，與 momentum 完全無關。不可因 momentum 為 null 就否定第一層的結果。

論述撰寫規則：
- 全部使用繁體中文，嚴禁引用英文原文（管理層用語需翻譯後再引述）
- 說明管理層使用了哪些成熟語言（翻譯為中文）、幾處
- 說明敘事處於什麼階段（計畫期/過渡期/成果期）
- 控制在 3-5 句內

## Output Format
```json
{
  "result": true,
  "emerging": false,
  "rationale": "管理層使用 5 處成熟語言，包括描述營收成長動能、獲利交付、經常性收入、營運槓桿與毛利率擴張等，超過 3 處門檻。敘事已從計畫期進入成果期，市場較容易給予更高估值倍數。"
}
```
