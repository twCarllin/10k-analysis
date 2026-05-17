---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_earnings_call

## Purpose
分析日本企業法說會（決算説明会）逐字稿，評估管理層的敬語強度、前瞻承諾層級、Q&A 訊號，萃取關鍵議題供投資研究參考。

## Input
- `transcript`（必填）：`logmi_parser.parse_logmi_transcript` 回傳的 dict，含以下欄位：
  - `title`：法說會標題
  - `date`：發表日期（字串）
  - `presentation`：管理層簡報段落（字串）
  - `qa`：Q&A 清單，每條含 `question` / `answer` / `asker` / `answerer`
- `prior_transcript`（選填）：上次法說會的同格式 dict，用於管理層基調對比
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. **會議摘要（meeting_summary）**：以 200 字以內繁體中文概述本次法說會的核心主題與管理層強調重點。引用日文短語時加括號標注，不大段逐字翻譯。
2. **前瞻 guidance（forward_guidance）**：萃取管理層對下半年或來期的具體承諾。依以下敬語層次判斷承諾強度（commitment_strength）：
   - 「達成すべく取り組んでまいります」→ `"high"`（明確承諾、積極推進）
   - 「達成に向けて努力してまいります」→ `"medium"`（努力方向、非保證）
   - 「目指してまいります」→ `"low"`（方向性表態、無具體承諾）
   - 若無前瞻陳述，`commitment_strength` 填 `null`
3. **Q&A 訊號（qa_signals）**：對每個 Q&A 配對分析：
   - 問題是否被正面回答（`answered: true/false`）
   - 回覆敬語強度（`response_strength: high/medium/low/evasive`）
   - 若 `answered: false` 或 `response_strength: "evasive"`，記入 `evasion_signals`
4. **主要關切議題（top_concerns）**：整理分析師最常追問或語氣最強的 3–5 個主題，每個含 `question_theme`（主題名稱）與 `summary`（一句概述）。
5. **與前次基調對比（tone_vs_prior）**：若有 `prior_transcript`，比較管理層措辭強度、議題重心是否移動；若無則填 `null`。
6. **劃界（Scope Boundaries）**：本 skill 只分析法說會逐字稿的口頭表達，不重述財務數字（財務數字由 jp_financial_analysis 處理），不重新評估書面有報的風險章節（由 jp_risk_analysis 處理）。若 presentation 段落與有報措辭高度雷同，只萃取法說會特有的補充說明。
7. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "meeting_summary": "200字以內的法說會概述",
  "forward_guidance": {
    "summary": "前瞻承諾摘要",
    "commitment_strength": "high|medium|low|null",
    "key_statements": ["具體承諾句1", "具體承諾句2"]
  },
  "qa_signals": [
    {
      "question_theme": "",
      "answered": true,
      "response_strength": "high|medium|low|evasive",
      "asker": "",
      "note": ""
    }
  ],
  "evasion_signals": [
    {"question_theme": "", "reason": ""}
  ],
  "top_concerns": [
    {"question_theme": "", "summary": ""}
  ],
  "tone_vs_prior": "與上次法說會基調對比（有 prior_transcript 才填，否則 null）",
  "insufficient_data": false
}
```
