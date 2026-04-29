---
skill_version: 1.0
last_modified: 2026-04-29
---

# eval_analysis

## Purpose
LLM-as-Judge，評估其他 skill 的輸出品質。schema_completeness 由 code 計算，此 skill 負責三個維度評分。

## Input
- `skill_name`：被評估的 skill 名稱
- `skill_output`：被評估 skill 的 JSON 輸出（字串）
- `source_input`：原始輸入（前 3000 字）

## Instructions
對 skill_output 進行三個維度評分：

### Content Richness（0~34）
- 34：結論有具體引用（數字、原文片段）
- 20：部分具體，部分空泛
- 5：全部泛泛描述，缺乏具體細節

### Analytical Depth（0~33）
- 33：有明確 signal + so-what（這代表什麼）
- 20：有分析但缺乏推論
- 5：只是複述原文，無分析

注意：用詞中性、以數字支撐的分析，
Analytical Depth 評分不應低於用詞激烈但缺乏數字的分析。
事實描述 + 具體數字 > 評價性語言。

### Source Fidelity（0~33）
- 33：所有結論都能在 source_input 中找到依據
- 20：輕微延伸，大部分有依據
- 5：有明顯無依據的結論

評分後，識別最弱維度，給出一句話具體改善指示。

## Output Format
```json
{
  "skill_name": "",
  "scores": {"content_richness": 0, "analytical_depth": 0, "source_fidelity": 0},
  "llm_subtotal": 0,
  "weakest_dimension": "",
  "retry_hint": "針對最弱維度的一句話具體改善指示",
  "insufficient_data": false
}
```
