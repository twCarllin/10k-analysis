---
skill_version: 1.3
last_modified: 2026-10-11
---

# tw_accounting_qa

## Purpose
回答台灣上市櫃公司財報的會計問題（例如「本季影響 FCF 最多的是什麼？」「毛利率為什麼下降？」）。先把問題對應到事實包的主題，再用主題內的數字寫答案。本 skill 不做算術：答案中每個數字都會被程式比對事實包，對不上就退回。

## Input
- `question`（必填）：使用者問題原文
- `company`（必填）：公司代號與名稱
- `topics_catalog`（必填）：可選主題清單 JSON（`key`、`name`）
- `facts_json`（必填）：事實包 JSON。`context` 為期間、口徑（basis；`H1`＝半年報 1–6 月累計）、核閱／查核、`ifrs17_break`、`ttm_status`／`ttm_reason`（近四季 TTM 可不可用與原因）；`topics` 以主題 key 為索引。金額已換算為「億元」字串，比例已換算為「%」字串，每列附頁碼 `page`
- `retry_hint`（選填）：上次輸出未通過檢查的原因（對不上的數字、不存在的主題）

## Instructions
1. 對應主題：從 `topics_catalog` 選出回答問題需要的主題 key（1–3 個），寫入 `topics`。只能用清單內的 key。
   - 問 FCF／自由現金流「多少」「影響最多」「為什麼變動」→ `fcf_analysis`（若清單有）
   - 問某項比率或金額 → 該指標 key；問「為什麼變動」「誰影響」→ 另加對應的 `bridge:<target>`（例如淨利 → `bridge:net_income`、營業利益 → `bridge:operating_income`）
   - 問毛利「為什麼變動」→ `bridge:gross_profit`（營收變動、成本變動）；問毛利率「為什麼上升／下降」→ `gross_margin` 加 `bridge:gross_margin`（營收變動效果、成本變動效果，單位百分點）
   - 問「近四季」「TTM」「過去 12 個月」「最近一年」→ `ttm:values`（TTM＝FY 年度數＋H1 本期−H1 去年同期）、`ttm:<指標 key>`（current＝TTM、prior＝FY 年度）、`ttm:bridge:<target>`（TTM vs FY 的營業利益／淨利變動）。`context.ttm_status` 不是 `ok` 時沒有 `ttm:*` 主題，依步驟 2 回答無法回答，並寫出 `ttm_reason`
   - 金控問集團資本適足率、逾放比、備抵呆帳覆蓋率 → `group_car`、`npl_ratio`、`coverage_ratio`。數字出自財報附註，引用時寫 `source` 的頁碼與銀行名；`stale` 為 true 時註明不是最新一期；值為「—」時寫出 `source.reason`
2. 問題無法用清單內主題回答 → `supported` 填 false、`topics` 填 []，`answer` 用一句話說明無法回答與可回答的範圍，**不寫任何數字**。
3. 寫答案（繁體中文）：
   - 第一句直接回答問題（結論）；其後列出依據，每個依據附頁碼（寫成 `p.N`）
   - **數字只能照抄 `facts_json` 中所選主題的字串**（含單位「億元」「%」「百分點」「天」「倍」），不可自行加減乘除、換算單位、四捨五入到其他位數，也不可引用未選主題的數字
   - 變動歸因用事實包已排序的結果（|變動| 大者在前）；說明「影響最多」時引用該項的變動與占比
   - 比率型指標的變動單位用「百分點」
   - 方向詞（增加、減少、上升、下降、提高、降低、成長、衰退、擴大、縮小、下滑、回升）後面緊接的數字必須是事實包的變動值（`delta`），且方向與正負號一致（正值＝增加／上升，負值＝減少／下降）；寫期末水準時用「增加至」「下降到」。成本或流出類（兩期皆為負值）可描述項目本身（「流出增加」）或對合計的影響（「使 CFO 減少」）
   - 支出與費用要寫清方向（金額取事實包 `current`／`prior`／`delta` 的絕對值，照事實包的億元字串寫，方向用「增加／減少」表示；不可自行加減）：
     - FCF 的資本支出（`key` 為 capex，兩期皆為負值）寫成「資本支出：本期支出 X、去年同期支出 Y，支出增加（減少）Z 億，使 FCF 減少（增加）Z 億（p.N）」，不可把負值寫成「資本支出減少」
     - bridge 的費用類組成項（cogs、selling_expenses、admin_expenses、rd_expenses、total_opex、other_opex_residual〔合成項，名稱「其他營業費用」〕、finance_costs、income_tax；值為負數）寫成「費用增加（減少）Z 億，使〈目標名稱〉減少（增加）Z 億」；`income_tax` 為正值（所得稅利益）時寫成「所得稅利益增加（減少）Z 億，使〈目標名稱〉增加（減少）Z 億」，不可寫成費用
     - 收入與損益類組成項照原寫法（「變動 Z 億元」）；「其他營業外收支」（合成項，`synthetic: true`）與「停業單位損益」（`discontinued_ops`，名稱照帳本）也用此寫法
     - bridge 的 `residual` 絕對值 ≥ 0.005 億（500 仟元，四捨五入後不為 0.00）時，一定要寫「未歸類項目 X 億」（取絕對值）；小於此值不寫
   - 程式核對認得的單位：億元、萬元、兆元、仟元、千元、百萬元、%、百分點（pp）、天、倍
   - basis 為 `H1` 時須註明：半年報只有 1–6 月累計數，「本季」「今年」皆以上半年累計回答；比率未年化
   - 註明核閱或查核；`ifrs17_break` 為 true 時註明去年同期為 IFRS 17 重編數，損益比較可能不一致
   - 用 `ttm:*` 主題時，寫明 TTM 迄日與比較的 FY 年度，並註明 TTM 由年報 FY 數（查核）與半年報數（核閱）組成；`ttm:values` 有 `comparability_note` 時照寫
4. 有 `retry_hint` 時，優先修正 hint 指出的問題。
5. 語氣依 `agents/analyst_agent.md`：事實描述，不用評價詞。

## Output Format
```json
{
  "supported": true,
  "topics": ["fcf_analysis"],
  "answer": "答案全文（純文字，可含換行）"
}
```
