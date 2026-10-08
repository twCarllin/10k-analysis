---
skill_version: 1.0
last_modified: 2026-04-27
---

# competitor_mapping

## Purpose
從 10-K Item 1 抽取結構化的競爭對手清單與公司市場定位，評估揭露品質，並支援 Q1 10-Q 的「去年 10-K baseline」模式。

## Input
- `current_section`（必填）：10-K 模式下為當期 Item 1 全文；Q1 模式下透過 orchestrator 的 `item1_prior_as_current → current_section` 映射，實際內容是去年 10-K Item 1（skill 本身只需讀 `current_section`，不需知道映射細節）
- `prior_section`（選填）：前一年 10-K Item 1（10-K 模式 yoy 比較用）；Q1 模式下不傳（為空）
- `mode`（選填）：`"normal"`（10-K 預設）或 `"q1_vs_10k"`（Q1 baseline 模式）；由 orchestrator 透過 `extra_inputs` 注入
- `prior_year`（選填）：Q1 模式下為去年年份字串（如 `"2025"`），用於 `baseline_note` 文案；由 orchestrator 透過 `extra_inputs` 注入
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. **抓 named competitors**：識別公司在 `current_section` 中明確點名的競爭對手。每個對手輸出：
   - `name`：公司名稱
   - `ticker`：若可從上下文推得則填入，否則留空
   - `markets`：該對手與本公司競爭的業務線或終端市場（list）
   - `note`：補充說明（如競爭強度描述、特殊關係等），可留空
   - 若 `current_section` 完全未提及競爭對手，`named_competitors` 輸出空 list，`insufficient_data` 設為 true

2. **評估市場定位**（market_position）：根據公司自我描述，判斷其在主要市場的地位：
   - `leader`：明確自稱市場領導者、最大供應商、市佔第一
   - `challenger`：第二大或挑戰市場領導者
   - `niche`：專注特定利基市場、特定客群
   - `follower`：無明確定位主張或跟隨競爭者
   - 同時輸出 `market_position_evidence`：一句引自原文的 evidence quote

3. **揭露品質評級**（disclosure_quality）：
   - `high`：明列多個具名對手 + 各自市場 + 競爭強度描述
   - `medium`：有具名對手但缺乏市場細分或競爭強度說明
   - `low`：僅泛泛描述競爭環境、迴避具名、或極少提及競爭
   - 同時輸出 `disclosure_rationale`：一句解釋評級理由

4. **yoy 變化**（10-K 模式，`mode == "normal"` 且有 `prior_section` 時）：對比 `current_section` 與 `prior_section`，為每個 competitor 標記：
   - `new`：今年新出現、去年未提及
   - `removed`：去年有、今年無
   - `unchanged`：兩年皆有
   - 若無 `prior_section`，所有 competitor 的 `yoy_status` 設為 `"unchanged"`

5. **Q1 模式特殊處理**（`mode == "q1_vs_10k"` 時）：
   - 所有 competitor 的 `yoy_status` 設為 `"baseline"`（表示此為基準年資料，非 yoy 比較）
   - `mode` 欄位輸出 `"q1_vs_10k"`
   - `baseline_note` 輸出：`"競爭格局基準來自 {prior_year} 10-K，下次更新於下年度 10-K"`（將 `{prior_year}` 替換為實際年份；若 `prior_year` 未傳入，使用 `"前一年度"`）
   - `disclosure_quality` 沿用 baseline 資料的評級（正常執行步驟 3）

## Output Format
```json
{
  "named_competitors": [
    {"name": "", "ticker": "", "markets": [], "yoy_status": "new|removed|unchanged|baseline", "note": ""}
  ],
  "market_position": "leader|challenger|niche|follower",
  "market_position_evidence": "",
  "disclosure_quality": "high|medium|low",
  "disclosure_rationale": "",
  "mode": "normal|q1_vs_10k",
  "baseline_note": "",
  "insufficient_data": false
}
```
