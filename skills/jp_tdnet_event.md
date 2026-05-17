---
skill_version: 1.1
last_modified: 2026-05-17
---

# jp_tdnet_event

## Purpose
對單一 TDNET 公告（適時開示）進行事件分類與信用影響評估。若有 `pdf_text`，主要依此分析；否則僅依標題與分類代碼判斷。

## Input
- `title`（必填）：TDNET 公告標題，如「2026年3月期 決算短信〔日本基準〕（連結）」
- `category`（必填）：由 `classify_tdnet_title` 自動分類的事件類別，如 `earnings_flash`、`guidance_revision`、`share_buyback` 等
- `company_name`（必填）：公告公司名稱（日文，TDNET 原始格式）
- `pdf_text`（選填）：從 PDF 解析出的純文字內容（最多 12000 字）。若有此欄位，主要依此進行分析；否則只用 title 做分類 + 預期影響
- `is_amendment`（選填）：是否為訂正公告
- `retry_hint`（選填）：eval 回饋的改善指示

## Instructions
1. 事件確認（event_category）：依 `category` 欄位對應事件類型，使用以下標準對應規則：
   - `earnings_flash` → 決算短信（季報/全年財報）
   - `guidance_revision` → 業績預測修正
   - `monthly_revenue` → 月次收益揭露
   - `share_buyback` → 自家股購回
   - `share_split` → 股票分割/合并
   - `equity_issuance` → 增資或新股發行
   - `capital_alliance` → 資本業務合作
   - `ma` → 合併收購或股份交換
   - `earnings_other` → 其他業績相關公告
   - `amendment` → 訂正公告（同時標記 is_amendment 為 true）
   - `other` → 其他公告
2. 依 `category` 分支分析重點（若有 `pdf_text`，從中提取；否則依標題推斷）：
   - `earnings_flash`：抽取營收（売上高）、營業利益（営業利益）、淨利（当期純利益）對比前期 YoY 變化幅度；通期業績予想（若揭露）；segment 別表現（若揭露）；管理層敬語強度（見下方）
   - `guidance_revision`：抽取修正前後數字、修正原因（管理層說法）、修正幅度對信用的潛在影響
   - `share_buyback`：抽取金額上限、股數上限、占發行股比例、執行期間
   - `ma`：抽取對象公司名稱、交易金額、戰略 rationale
   - `other` / 不明：短摘要 + 提醒需人工 review
3. 重要性評估（materiality）：
   - `high`：決算短信、業績大幅修正、M&A、增資
   - `medium`：業績預測修正（幅度不明）、月次收益、自家股購回
   - `low`：訂正小幅公告、一般資訊揭露
4. 信用面影響（credit_impact）：
   - 決算短信本身屬中性（不知道內容好壞）→ `"neutral"`；若 pdf_text 顯示業績遠優於預期 → `"positive"`；若遠低於預期 → `"negative"`
   - 增資、M&A 依情境 → `"unclear"`（無具體資訊時）
   - 自家股購回 → 通常正面 → `"positive"`
   - 若確定無法判斷 → `"unclear"`
5. 訂正標記（is_amendment）：若 `category` 為 `amendment` 或標題含「（訂正）」「（更正）」前綴，標記為 true。
6. key_metrics（earnings_flash / guidance_revision 重點填寫）：
   - 從 pdf_text 中提取具體數字（單位注意：決算短信通常以百万円或億円為單位，以文件內標示為準）
   - 若無 pdf_text 或找不到具體數字，對應欄位填 null
   - revenue：当期売上高（或営業収益）的實際金額（字串，帶單位）
   - operating_income：営業利益的實際金額
   - net_income：当期純利益的實際金額
   - yoy_pct：與前期同期相比的增減幅（如「+12.3%」「▲5.2%」）
   - annual_forecast：通期業績予想（若有揭露，包含金額與是否維持/修正）
7. forward_guidance：摘述管理層對未來業績的具體承諾或展望（1–2 句繁中，含敬語強度評估）。無前瞻陳述時填 null。
8. segment_notes：若 pdf_text 有 segment 別揭露，每個 segment 一筆 {name, performance}；無則空陣列。
9. pdf_extracted：boolean，標示是否使用了 pdf_text 進行分析（有 pdf_text 且成功提取資訊 → true；否則 → false）。
10. 事件摘要（event_summary）：以 1–2 句繁體中文描述此公告的事件意義。若有具體業績數字，直接帶入摘要。
11. JSON value 一律使用繁體中文，不大段引用日文原文（但可引用日文短語當例證）。

## 注意事項
- 若 `title` 或 `category` 不足以判斷，在相關欄位填 `null` 或 `"unclear"`，不可捏造數字
- pdf_text 可能有換行不整齊、數字前後有空格等格式問題，解析時要容錯
- key_metrics 中的數字應保留單位標示（如「52,345 百万円」），不要自行換算

## Output Format

```json
{
  "event_category": "決算短信",
  "materiality": "high",
  "credit_impact": "neutral",
  "is_amendment": false,
  "event_summary": "本公告為年度決算短信，揭露全年財務結果。",
  "key_metrics": {
    "revenue": null,
    "operating_income": null,
    "net_income": null,
    "yoy_pct": null,
    "annual_forecast": null
  },
  "forward_guidance": null,
  "segment_notes": [],
  "key_terms": {},
  "verbatim_quote": null,
  "pdf_extracted": false,
  "insufficient_data": false
}
```
