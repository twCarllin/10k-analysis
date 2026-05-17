---
skill_version: 1.0
last_modified: 2026-05-17
---

# jp_extraordinary_event

## Purpose
分析臨時報告書（臨時報告書）所揭露的單一重大事件，評估事件的信用面影響與重要性，提供投資者決策參考。

## 原則
- 臨時報告書內容通常極短（< 5,000 字），聚焦單一事件。
- `event_type_guess` 是系統的啟發式推測，最終分類以 `event_category` 為準，由 LLM 判斷。
- 信用影響評估以「對公司信用品質的實質影響」為準，而非市場情緒。
- 若 narrative 為空或不足，回傳 `{"insufficient_data": true}`。

## Input
- `narrative`（必填）：`extract_rinji_event` 抽出的合併文字（日文）
- `event_type_guess`（必填）：系統推測的事件類別（`ma_or_capital` / `executive_change` / `lawsuit_or_other` / `shareholder_resolution` / `unknown`）
- `form_code`（必填）：EDINET 申報 form code（如 `053000`）
- `retry_hint`（選填）：eval 回饋建議

## Instructions
1. 閱讀 `narrative`，識別事件的核心內容：
   - 事件發生日期、涉及對象（公司 / 個人 / 資產）
   - 事件的主要條款（金額、股數、契約內容、法律爭議金額等）
   - 管理層在揭露中的措辭立場（說明型 vs 防禦型 vs 主動揭露型）
2. 判斷 `event_category`：
   - M&A / 股份取得 / 重大資產處分 → `"M&A"`
   - 增資 / 公司債 / 資本結構變動 → `"capital"`
   - 定時 / 臨時股東大會決議 → `"shareholder_resolution"`
   - 重大訴訟 / 行政處分 → `"lawsuit"`
   - 天災 / 生產中斷 → `"disaster"`
   - 役員異動（取締役選任 / 辭任） → `"executive"`
   - 重大契約（供應 / 合作 / 授權） → `"contract"`
   - 訂正報告 / 開示修正 → `"disclosure_correction"`
   - 其他 → `"other"`
3. 評估 `materiality`（對公司信用 / 財務的重要性）：
   - `"high"`：影響核心業務、大額資金流動（>10% 資本）、或重大法律責任
   - `"medium"`：有一定影響但可管理，例如中型訴訟、局部業務調整
   - `"low"`：常規性揭露，例如定時股東大會董事改選
4. 評估 `credit_impact`（對信用品質的影響方向）：
   - `"positive"`：增強財務彈性、強化核心業務
   - `"neutral"`：常規性事件，不實質影響信用評估
   - `"negative"`：增加負債、損耗現金或引發法律不確定性
   - `"unclear"`：資訊不足，無法判斷
5. 提取 `key_terms`：從 narrative 中抽出最關鍵的 3–5 個具體數字或條款（金額、日期、對象名稱）
6. 選取 `verbatim_quote`：最能代表事件核心的日文短句（< 100 字）
7. 不分析公司的歷史業績或長期策略；不重複 jp_mdna / jp_risk 已覆蓋的常規風險
8. 所有 JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）

## Output Format
```json
{
  "event_category": "M&A|capital|shareholder_resolution|lawsuit|disaster|executive|contract|disclosure_correction|other",
  "event_summary": "事件摘要（200 字內，繁中）",
  "materiality": "high|medium|low",
  "credit_impact": "positive|neutral|negative|unclear",
  "key_terms": {
    "金額": "（若有）",
    "對象": "（若有）",
    "時程": "（若有）"
  },
  "verbatim_quote": "最重要的日文短句原文",
  "insufficient_data": false
}
```
