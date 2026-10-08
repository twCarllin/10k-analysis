---
skill_version: 1.0
last_modified: 2025-04-23
---

# section_splitter

## Purpose
LLM fallback，識別各 Item 起始句子。當 header-based 和 TOC-guided 切割都失敗時，由此 skill 辨識文件中各 Item 的起始位置。

## Input
- `document_preview`：文件前 8000 字
- `full_text_length`：全文總字數

## Instructions
1. 閱讀 document_preview，識別以下 Item 的起始句子：
   - item1: Item 1 — Business
   - item1a: Item 1A — Risk Factors
   - item1c: Item 1C — Cybersecurity
   - item7: Item 7 — MD&A
   - item8: Item 8 — Financial Statements
   - item9a: Item 9A — Controls and Procedures
   - item10: Item 10 — Directors
   - item11: Item 11 — Executive Compensation
   - item13: Item 13 — Certain Relationships
2. 對每個找到的 Item，提取該 Item 正文的第一句話作為 anchor
3. anchor 必須來自正文，不是目錄（TOC）中的引用

## Output Format
```json
{
  "item_anchors": {
    "item1": "原文第一句...",
    "item1a": "原文第一句..."
  },
  "insufficient_data": false
}
```
