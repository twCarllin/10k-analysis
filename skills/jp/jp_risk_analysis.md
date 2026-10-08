---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_risk_analysis

## Purpose
分析日本有価証券報告書「事業等のリスク」章節（jpcrp_cor:BusinessRisksTextBlock），萃取風險清單、重要性排序與跨期變動。

## 原則
風險分析的唯一目的是：讓投資者知道「現在有哪些風險，各自有多大」。新增/持平的分類是次要資訊，不應成為呈現的主軸。

## Input
- `current_section`（必填）：當年「事業等のリスク」日文原文（TA4 `split_filing_by_ixbrl` 的 `risk` key，建議 caller 先跑 `split_risk_section()` 得到 items list，每個含 title + body）
- `prior_section`（選填）：前一年同章節日文原文，用於跨期 delta 比較
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 列出所有風險項目，每項包含：title（原日文標題，可附繁中譯）/ description（50 字以內繁中描述）/ category（macro / regulatory / operational / financial / legal / supply_chain）/ importance（high / medium / low）。`supply_chain` 類別依是否涉及原料 / 零件 / 物流中斷判斷，不依敬語層次。
2. importance 判斷規則：優先依敬語層次判斷，規則如下：
   - 「リスクがあります」（可能存在）→ `"low"`
   - 「リスクが高まっています」（正在升高）→ `"medium"`
   - 「リスクが顕在化する可能性があります」（可能具體化）→ `"high"`
   - 若無上述敬語線索，依篇幅佔比與排序位置判斷（排序靠前、篇幅較長者重要性較高）。
3. 前 3 大風險（top_3）：依 importance 輸出，每個附 rationale 說明入選理由。
4. 若有 prior_section（選填，最後做）：記錄有實質變化的項目（新增或措辭明顯加重）。跨年 delta 同時評估整體風險輪廓與條目級變化：
   - 條目措辭從「リスクがあります」升級為「リスクが顕在化する可能性があります」→ 視為「強化」
   - 前期出現、本期未出現的風險 → 視為「移除」
   - 整體摘要填入 delta_summary（一句話描述整體方向）。
5. **劃界（Scope Boundaries）**：本 skill 只分析風險條目的性質與重要性。不分析管理層 guidance 或業績展望（屬 jp_mdna_analysis 範圍）；不描述 R&D 主題或供應鏈業務結構（屬 jp_business_analysis / jp_rd_analysis 範圍）。只判斷「這是什麼風險、有多大」，不延伸分析因應措施是否有效。
6. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## Output Format
```json
{
  "risks": [
    {
      "title": "",
      "description": "",
      "category": "macro|regulatory|operational|financial|legal|supply_chain",
      "importance": "high|medium|low"
    }
  ],
  "top_3": [
    {"title": "", "rationale": ""}
  ],
  "delta_summary": "整體風險輪廓與前期相比（有 prior 才填，否則 null）",
  "insufficient_data": false
}
```
