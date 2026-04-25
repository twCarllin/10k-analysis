---
skill_version: 1.0
last_modified: 2025-04-25
---

# rerate_structure

## Purpose
判斷公司營收結構是否正在轉型：高毛利部門佔比是否持續上升。

## Input
- segment_summary（必填）：segment_trend agent 輸出的 JSON 字串
- retry_hint（選填）

## Instructions

根據 segment_summary 的事實數據，判斷營收結構是否在轉型。

判斷規則：
1. 在 segment_table 中找出所有 margin_quality == "high" 且 direction == "rising" 的部門
2. 其中任一部門的 revenue_pct 在最近 2 年內上升超過 5 個百分點 → true
3. 否則 → false
4. 若 segment_table 為空或 insufficient_data == true → false

論述撰寫規則：
- 全部使用繁體中文，嚴禁引用英文原文
- 用具體數字佐證（營收金額、佔比變化、成長率）
- 控制在 3-5 句內，直接說結論和依據

## Output Format
```json
{
  "result": true,
  "rationale": "資料中心部門毛利率高且持續上升，營收佔比從 38% 升至 45%（兩年增加 7 個百分點），超過 5 個百分點門檻。公司營收結構正從傳統 PC 為主，轉向高毛利的資料中心與 AI 業務。"
}
```
