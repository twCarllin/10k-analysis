# Spec：半年報期間模型＋損益 TTM（工作包 C，`tw-equity`）

> run_id：`2026-10-09-tw-equity-period-model`。前序：`spec/2026-10-09-tw-equity-statements.md`（帳本）、`spec/2026-10-09-tw-equity-metrics.md`（指標，下稱「指標 Spec」）、`spec/2026-10-09-tw-equity-fs-generalize.md`（三表泛化，下稱「泛化 Spec」）。研究依據：`docs/research/2026-10-09_00_summary.md` §3「分析層」、§4 工作包 C。
> 本 Spec 自足：不依賴對話。

---

## 0. 定位

### 0.1 目標
1. **期間模型**：帳本（`StatementLedger`）明確記錄每一期的期間、天數、比較基準與確信等級（`assurance`），讓 metrics 不再混用不同時點的數字。
2. **修正半年報期間錯配**（現況 bug）：半年報的 IS／CF prior 欄是上年同期（114H1），BS prior 欄是上年度末（114-12-31）。指標的 prior 期把兩者混用；天數指標（DSO／DIO／DPO）把半年數字乘 365，約大 2 倍。
3. **FY 損益來源**：從 2025 年報的「財務績效比較分析表」（下稱 FY 損益表）解析 FY2025（民國 114 年）與 FY2024 的損益科目。現有 `tables.parse_two_year_table`（T7b）在 37 份年報中只有 2 份可用（實測見 §0.4）。
4. **損益 TTM**：TTM = FY2025 ＋ 2026H1 − 2025H1，只做損益科目（年報沒有完整現金流量表，CF 類 TTM 不做）。指標與 bridge 加一組「TTM vs FY2025」視圖。

### 0.2 範圍（使用者 2026-10-09 裁示）
- TTM 只做損益；FY2025 來源＝年報 FY 損益表；本 run 一併做 FY 損益表的錨點與解析泛化。
- 半年報 BS 的比較基準**兩欄都保留**：比率類指標的 prior 期用 BS「上年同日」欄（114-06-30，與 IS／CF 的 114H1 同期）；BS 類 bridge（`total_assets`）的 prior 用「上年度末」欄（114-12-31，IAS 34 慣例）。
- **金控**（2881、2882、2884、2885、2886、2887、2891）不在本 run（工作包 E）。金控的 FY 損益表結構不同（淨收益、呆帳費用），本 run 對金控輸出 TTM 不可用。
- **不打外部 API**（無 OCR、無 LLM）。

### 0.3 驗收門檻
- **FY 損益表**：§4 列的 30 份非金控年報中 **≥27 份**達到 §2.6 的「可用」判準（使用者 2026-10-09 裁示）。G12 的 2344、2345、3711 若確實無 FY 損益比較表，其餘 27 份須全數可用。未達的每一份在驗收報告逐檔寫出根因一句與建議工作包。
- **正確性錨**：3653 年報 FY 損益表解析出的 114 年度 `revenue`、`cogs`、`gross_profit`、`operating_income`、`pretax_income`、`income_tax`、`net_income`，與 `tw_report/3653_2025Q4合併財報.pdf` 帳本的 current 值**逐項相等**（以 §2.4 符號正規化後比較，容差 0）。
- **三表驗收不退步**：`runtime.tw_equity.fs_acceptance` 維持 26/29。
- 既有測試全部通過（`./.venv/bin/python -m pytest -q`）。

### 0.4 實測事實（2026-10-09）

| # | 現象 | 例 |
|---|---|---|
| G1 | 現有 T7b（錨點 `ar_fin_performance`＋`parse_two_year_table`）37 份年報只 2 份解析出損益（3653、7769）：找不到錨點 9 份、錨點有但解析失敗 20 份、取到錯的表 6 份（2317、2327、2368 取到資產負債表；2885 取到薪資表） | — |
| G2 | 年度欄順序不固定：114 在前（1303、2317）或 113 在前（2301、2327、2382、2454） | 2301：`113年度 114年度 增(減)金額 變動比例%` |
| G3 | 年度寫法變體：`114年度`、`114年`、`民國114年` | 2330：`民國114年 民國113年 增減金額 增減比率(%)` |
| G4 | 有些表每年度帶 `%` 欄（金額、% 成對） | 3653：`項目 金額 % 金額 %`；7769 同 |
| G5 | pdfplumber 把整張表擠在同一格（以換行分隔），以表格為單位解析會失敗；以頁的文字列解析正常 | 2408、3008、8046 |
| G6 | 金額有 `$` 前綴、括號負數、`-` 負號；列尾有 `說明1`、`(註1)`、`(註2)` 等附註 | 2308：`營業收入淨額 $554,885,168 $421,147,557 $133,737,611 32 說明1` |
| G7 | 科目寫法變體：`營業收入淨額`、`營業收入總額`（下一列 `減:銷貨退回及折讓`、再下一列 `營業收入淨額`）、`合併營業收入`、`營業損益`、`營業淨利(損)`、`稅前利益`、`本期稅前淨利`、`減:所得稅費用`、`稅後淨利`、`營業損失` | 8046、2383、2382、7769、3008、2026 |
| G8 | 與資產負債表比較表左右並排在同一頁（同一列左邊是 BS 科目、右邊是 IS 科目） | 4958：`流動資產 132,508,624 127,641,143 -4,867,481 -3.67% 營業收入 171,663,845 182,…` ；3443 同 |
| G9 | 同一份年報有多個候選頁：致股東報告書內的摘要表（科目少）與第柒章的完整表 | 2383（頁 5、87）、3017（頁 4、107）、2368（頁 5、6、105） |
| G10 | 基礎（合併／個體）：多數頁未寫；寫明者為「合併財務績效比較分析表」「台積公司及子公司財務報表」 | 2357、3037、2330 |
| G11 | 單位：`新台幣仟元`、`新台幣千元`、`千元`、`百萬新台幣`（2317 的 T7a）| — |
| G12 | 找不到 FY 損益比較表的候選頁：2344、2345（以 §2.2 規則初篩 0 頁）；3711 只有文字敘述 | — |

### 0.5 不碰的既有檔案
`runtime/tw_credit/**`、`runtime/orchestrator.py`、`runtime/jp_*.py`、`runtime/agent_runner.py`、`runtime/report_writer.py`、`skills/**`、`agents/**`、`main.py`、`runtime/tw_equity/pdf_doc.py`、`runtime/tw_equity/doc_anchor.py`、`runtime/tw_equity/ocr.py`、`runtime/tw_equity/cross_year.py`、`runtime/tw_equity/tw_pipeline.py`、`runtime/tw_equity/inputs.py`、`tw_equity_inputs/**`。
**`tables.parse_two_year_table` 與 `bundle.fin_performance` 不改**（`cross_year.py` 與報告 T7b 節依賴其輸出）。FY 損益表用新模組解析，不取代 T7b。
允許改：`runtime/tw_equity/statements.py`、`runtime/tw_equity/metrics.py`、`runtime/tw_equity/tables.py`（只限 `extract_tables` 接線與 `TablesBundle` 新欄位）、`runtime/tw_equity/report.py`（只限附錄 E）；新檔 `runtime/tw_equity/fy_income.py`、`runtime/tw_equity/fy_acceptance.py`；`tests/tw_equity/**`；`tests/fixtures/tw_equity/**`。

---

## 1. 帳本期間模型（`statements.py`，向後相容）

### 1.1 `StatementLedger` 新增欄位（皆有預設值；`to_dict()` 輸出新鍵，既有鍵與值不變）
- `basis: str` — `"H1"`（IS 本期欄期間為 `YYY-01-01~YYY-06-30`）、`"FY"`（`YYY-01-01~YYY-12-31`）、`"other"`（其他或解析不到）。由 `column_periods["is"][current_col["is"]]` 判定；IS 無期間時改用 CF。
- `periods: dict[str, str | None]`，固定 5 鍵：
  - `flow_current`：IS 本期欄期間標籤（例 `"115-01-01~115-06-30"`）
  - `flow_prior`：IS 上期欄期間標籤（例 `"114-01-01~114-06-30"`）
  - `bs_current`：BS 本期欄時點（例 `"115-06-30"`）
  - `bs_prior_same`：BS 中與 `flow_prior` 迄日同日的欄（例 `"114-06-30"`）；無此欄 → None
  - `bs_prior_fy_end`：BS 中「本期年度 − 1」的 `-12-31` 欄（例 `"114-12-31"`）；無此欄 → None
  - 年度財報：`bs_prior_same` 與 `bs_prior_fy_end` 都是 `"113-12-31"`。
- `days: dict[str, int | None]` — `{"current": n, "prior": n}`，為 `flow_current`／`flow_prior` 的日曆天數（含起訖兩日；115H1 = 181，FY 平年 = 365，閏年 366）。期間解析不到 → None。
- `assurance: str | None` — 財報 PDF 前 5 頁文字含 `核閱報告` → `"reviewed"`；含 `查核報告` → `"audited"`；兩者都有取先出現者；都沒有 → None。

### 1.2 取值 helper
新增 `StatementLedger.value_at(key: str, tag: str) -> float | None`，`tag` ∈ {`"flow_current"`, `"flow_prior"`, `"bs_current"`, `"bs_prior_same"`, `"bs_prior_fy_end"`}：
- 依 key 第一個相符列所屬表（bs 用 bs_* tag；is／cf 用 flow_* tag）在 `column_periods` 找該標籤的欄索引，回傳 `row.columns[i]`。
- 表與 tag 不相容（例如 bs 列配 flow tag）、標籤為 None、欄不存在 → None。
- 列存在但該欄值為 None（財報的 `-`）→ 0.0（與 `metrics._ledger_value` 慣例相同）。無該 key 的列 → None。
- `columns` 為空（舊帳本或合成測試帳本）時：`flow_current`／`bs_current` 退回 `row.current`；`flow_prior`／`bs_prior_same`／`bs_prior_fy_end` 都退回 `row.prior`（與舊行為相同）。
- 新欄位預設值：`basis="other"`；`periods` 5 鍵皆 None；`days={"current": None, "prior": None}`；`assurance=None`。

---

## 2. FY 損益表解析（新檔 `fy_income.py`）

### 2.1 入口
`extract_fy_income(ar: PdfDoc, ar_anchors: dict | None, *, roc_year: int) -> FyIncome | None`。找不到候選頁 → None。

`FyIncome`（dataclass，`to_dict()`）：
- `roc_year: int`（本期民國年，例 114）
- `page: int`（來源頁，1-indexed）
- `unit: str`（原文）；`scale: float | None`（換算為仟元的倍數：`仟元`／`千元` → 1；`百萬元`／`百萬新台幣` → 1000；`元` → 0.001；認不出 → None）
- `basis: str` — `"consolidated"`（頁文字含 `合併` 或 `及子公司`）／`"parent"`（含 `個體` 且不含前兩者）／`"unknown"`
- `rows: list[dict]` — 每列 `{"label", "key", "current", "prior"}`（已乘 `scale`；`current`＝`roc_year` 欄，`prior`＝`roc_year − 1` 欄）
- `checks: list[dict]` — §2.5 的勾稽結果 `{"name", "lhs", "rhs", "passed"}`
- `usable: bool` — §2.6 判準
- `warnings: list[str]`
- `get(key) -> tuple[float | None, float | None]` — 第一個相符列的 (current, prior)；無 → (None, None)

### 2.2 候選頁
1. 掃全份年報每一頁的文字列。頁符合**全部**條件才是候選頁：
   a. 表頭區（第一個營收列之前）含 `{roc_year}年` 與 `{roc_year-1}年`（NFKC、去空白後比對；`民國` 前綴與 `度` 後綴都可）。
   b. 有一列的科目對照為 `revenue`（§2.4），且該列有 ≥2 個金額。
   c. 營收列之後 40 列內，至少再有 2 列的科目對照到 {`gross_profit`, `operating_income`, `pretax_income`, `net_income`} 之一且各有 ≥2 個金額。
2. 多個候選頁時依序選：①落在 `ar_anchors["ar_fin_performance"]` 或 `ar_anchors["ar_mdna"]` 頁範圍內者；②其餘候選頁中對照到 §2.4 key 數最多者；同數取頁碼較大者（致股東報告書在前、完整表在後，G9）。

### 2.3 列解析（以頁的文字列為單位，不用 pdfplumber 表格，G5）
- 年度欄順序：表頭中 `{roc_year}年` 與 `{roc_year-1}年` 的先後決定第 1、第 2 個年度欄各是哪一年（G2）。
- `%` 成對：表頭兩個年度標記之間出現 `%` → 每個年度佔 2 個 token（金額、%），取金額（G4）。
- 金額 token：千分位數字、`$` 前綴、括號負數、`-` 負號；列尾的 `說明N`、`(註N)`、`註N` 與變動比例欄忽略（G6）。只取每列前 2 個年度的金額。
- 左右並排（G8）：一列中出現「金額之後又有中文科目＋金額」→ 切成左右兩段，各自對照，只保留對照到 IS key 的段。
- 跨列科目（科目在上一列、金額在下一列）不處理，列入 warnings。

### 2.4 科目對照與符號
- 先剝除前綴 `合併`、`減:`／`減：`、`加:`／`加：`，再用 `statements.map_key("is", label, None)` 對照；對不到時用本模組的補充別名：
  - `營業收入總額` → `revenue`（**僅在同頁沒有其他列對照為 `revenue` 時**；8046 的 `營業收入總額`、`減:銷貨退回及折讓`、`營業收入淨額` 取 `營業收入淨額`）
  - `營業損益`、`營業淨利(損)`、`營業損失` → `operating_income`
  - `稅前利益`、`本期稅前淨利`、`稅前損益` → `pretax_income`
  - `稅後淨利`、`本期稅後淨利`、`本年度淨利` → `net_income`
  - `營業費用` → `total_opex`；`營業外收入及支出`、`營業外收入(支出)` → `nonoperating_total`
  - `營業毛利淨額` → `gross_profit_net`（`營業毛利` 仍為 `gross_profit`）
- 同 key 多列 → 取第一列。
- **符號正規化**（TTM 與勾稽前；正規化後費用為負、收入為正）：
  - `cogs`、`total_opex` 取 `-abs(x)`。
  - `income_tax` 依科目原文（同泛化 Spec §8.1.4「括號內的詞＝負值時的意義」）：含 `(費用)` → 原值；含 `(利益)` → `-x`；其他 → `-abs(x)`。帳本（H1）的 `income_tax` 列以同一規則正規化。
  - 其餘照原值（`營業損失 (12,314)` 為負值本身即正確）。

### 2.5 勾稽（兩期各一次；任一輸入 None → passed=None；容差 1 仟元）
- `gross`：`revenue + cogs == gross_profit`
- `operating`：`(gross_profit_net 有則用之，否則 gross_profit) + total_opex == operating_income`
- `net`：`pretax_income + income_tax == net_income`

### 2.6 可用判準（`usable=True` 需全部成立）
- `scale` 非 None；`basis` 不是 `"parent"`
- 本期（`roc_year`）的 `revenue`、`operating_income`、`pretax_income`、`net_income` 皆非 None
- §2.5 勾稽中沒有 `passed=False`

---

### 2.7 第二輪修正（使用者 2026-10-09 裁示；依 item 2.4 實跑 19/30 的根因）
1. **毛利勾稽**：`未(已)實現銷貨損益`、`未實現銷貨損益`、`已實現銷貨損益`（含 `減:`／`加:` 前綴）對照新 key `unrealized_sales_profit`。`gross` 勾稽：有 `gross_profit_net` 列時改驗 `revenue + cogs + unrealized_sales_profit == gross_profit_net`（`unrealized_sales_profit` 缺列視為 0）；另驗 `revenue + cogs == gross_profit`。兩式任一成立即 passed（1303）。
2. **營業利益勾稽**：`其他收益及費損`、`其他收益及費損淨額`、`其他營業收益及費損淨額` 對照 `other_operating_net`。`operating` 勾稽為 `(gross_profit_net 有則用之，否則 gross_profit) + total_opex + other_operating_net == operating_income`（`other_operating_net` 缺列視為 0）（2303、2330、2368）。
3. **排除個體頁**：§2.2 選頁前，先剔除頁文字含 `個體` 且不含 `合併`／`及子公司` 的候選頁；全部被剔除時才保留原候選（結果 basis 為 parent → 不可用）（2357、2454）。
4. **所得稅符號（無括號詞）**：同頁 `cogs` 原值為正（表內費用以正數表示）時，無括號詞的 `income_tax` 正規化為 `-x`（負值＝稅利益）；`cogs` 原值為負或缺列時維持 `-abs(x)`（8046）。
5. **單位往前找**：候選頁沒有單位列時，往前 1 頁找；仍無 → 改用該頁或前 1 頁敘述文字中「緊接千分位金額之後」的 `仟元`／`千元`／`百萬元`（NFKC、去空白後比對，例 `59,144,461仟元`）；多個不同單位同時出現 → scale None；全無 → scale None（2368；使用者 2026-10-09 裁示）。**同 key 多列**：僅取該頁「營收列所屬表」內的列——營收列之前出現的同 key 列不取（2368 頁首另一張表）。
6. **淨利代用**：頁內無 `net_income` 列、但有 `淨利歸屬於母公司業主`／`本期淨利歸屬於母公司業主`／`歸屬於母公司業主之淨利` 時，以該值作為 `net_income`，`FyIncome` 新增欄位 `net_income_basis: "total" | "parent"`（預設 `"total"`），warnings 記一句「net_income 以歸屬母公司淨利代用」（3017）。
   - §3.2 TTM：`fy_income.net_income_basis == "parent"` 時，`ttm["net_income"]` 的 H1 兩期改取帳本 `net_income_parent`（`value_at("net_income_parent", …)`），`TtmView.values["net_income"]` 加 `"basis": "parent"`。

## 3. 指標視圖（`metrics.py`）

### 3.1 主視圖（既有 `MetricsPack` 欄位，修正期間錯配）
- 既有 `current`／`prior` 兩期的取值改走 `ledger.value_at`：
  - IS／CF key：current → `flow_current`；prior → `flow_prior`
  - BS key：current → `bs_current`；prior → `bs_prior_same`（年度財報即上年度末）
- **BS 類 bridge**（`BRIDGE_SPECS` 中 target 為 `total_assets` 者）的 prior 改用 `bs_prior_fy_end`（使用者裁示：兩欄都保留）。
- **天數指標**（`dso`、`dio`、`dpo`）的 `365` 改為該期 `ledger.days[period]`；`formula` 字串同步改為 `* days`。days 為 None 時：帳本 `column_periods["is"]` 為空（舊帳本／合成帳本）→ 退回 365（舊行為）；否則 → 指標 None。
- `roe`、`roa`、`asset_turnover` 在主視圖**不年化**（H1 值就是半年值）；年化值看 TTM 視圖。
- `MetricsPack` 新增欄位並輸出到 `to_dict()`：`basis`、`days`、`assurance`、`periods`（照抄帳本）。

### 3.2 TTM 視圖（新）
- `compute_metrics(ledger, fy_income=None)`：新增選用參數。`MetricsPack` 新增 `ttm: TtmView | None`，`to_dict()` 新鍵 `"ttm_vs_fy"`。
- **可用條件**：`ledger.basis == "H1"`、`fy_income is not None`、`fy_income.usable`、`fy_income.roc_year == int(ledger.periods["flow_prior"][:3])`、帳本 `unit` 含 `仟元` 或 `千元`（否則 reason 為 `unit_mismatch`；`fy_income` 值已換算為仟元）。不成立 → `ttm = TtmView(status="unavailable", reason=<一句>, …其餘空)`；ledger basis 為 FY 時 `ttm = None`（TTM 即 FY 本身）。
- **TTM 損益**（key ∈ `TTM_KEYS` = `revenue`, `cogs`, `gross_profit`, `total_opex`, `operating_income`, `nonoperating_total`, `pretax_income`, `income_tax`, `net_income`）：
  `ttm[k] = fy[k] + h1_cur[k] − h1_prior[k]`；三者皆經 §2.4 符號正規化；任一 None → `ttm[k]` None。`h1_cur`／`h1_prior` 取 `ledger.value_at(k, "flow_current"／"flow_prior")`。
- **兩期**：`ttm`（TTM 損益＋BS `bs_current`）與 `fy`（FY2025 損益＋BS `bs_prior_fy_end`）。CF key 一律 None（CF 類指標為 None）。天數指標用 365。
- 指標：照 `METRIC_SPECS` 對兩期各算一次（輸出形狀同主視圖的 `metrics`）。
- bridge：只算 `operating_income`（組成 `revenue`、`cogs`、`total_opex`）與 `net_income`（組成 `revenue`、`cogs`、`total_opex`、`nonoperating_total`、`income_tax`），演算法同指標 Spec §2.2。
- `TtmView.to_dict()`：`{"status": "ok"|"unavailable", "reason", "period_ttm": "<flow_current 迄日>", "period_fy": "<roc_year>", "assurance": "mixed", "source_page": fy_income.page, "values": {key: {"fy", "h1_current", "h1_prior", "ttm"}}, "metrics": [...], "bridges": [...], "index": {...}}`。

---

## 4. FY 損益驗收（新檔 `fy_acceptance.py`）
- CLI：`./.venv/bin/python -m runtime.tw_equity.fy_acceptance [--out run/fy_acceptance.json]`
- 語料：`tw_report/` 內 30 份非金控 2025 年報（檔名寫成常數 `ACCEPTANCE_FILES`）：`<ticker>_2025年報.pdf`，ticker ∈ {1303, 2059, 2301, 2303, 2308, 2317, 2327, 2330, 2344, 2345, 2357, 2360, 2368, 2382, 2383, 2408, 2454, 3008, 3017, 3037, 3443, 3711, 4958, 5274, 6505, 6669, 7769, 8046}（28 份），加上 `2025_2926_年報pdf.pdf`、`2025_3653_健策年報.pdf`（2 份）。2412、2884 無年報；`3653_2024年報.pdf` 不列入。
- 每份：`load_pdf` → `find_annual_report_sections(required=set())` → `extract_fy_income(roc_year=114)`；輸出 page、basis、unit、scale、各 key 值、checks、usable、warnings。
- 3653 正確性錨（§0.3）一併檢查並輸出。
- 驗收報告寫入 `docs/research/2026-10-09_05_fy_income_acceptance.md`（逐檔表＋未可用檔的根因與建議工作包）。

## 5. 接線與報告
- `tables.extract_tables`：年報載入後呼叫 `extract_fy_income(ar, ar_anchors, roc_year=roc_year)`，存 `TablesBundle.fy_income`（`to_dict()` 鍵 `"fy_income"`）；`compute_metrics(statements, fy_income=fy_income)`。
- `report.py` 附錄 E：
  - 期間行改為顯示 `basis`、本期／上期期間標籤、天數、`assurance`。
  - 新增「### TTM vs FY」小節：status 為 ok 時列 TTM 損益組成表（FY、H1 本期、H1 上期、TTM）、指標表（TTM、FY）、2 個 bridge；unavailable 時一行寫 reason；`ttm` 為 None 時不輸出本小節。

## 6. 已裁示事項（使用者 2026-10-09）
1. FY 損益表驗收門檻：30 份中 ≥27 份可用（第二輪 §2.7 修正後重驗）。
2. `basis="unknown"` 視為可用（年報第柒章財務績效依準則以合併報表為主）；3653 正確性錨驗證此假設。
3. 主視圖 `roe`／`roa`／`asset_turnover` 不年化；年化值只在 TTM 視圖。
4. 工作目錄既有未提交檔案（`tw_equity_inputs/**`、`cache/`、`docs/research/`、`evidence/`、`gate1/`、`impact/`、`risk/2026-10-08-tw-equity-phase-1a.md`、`tw_report/`、`產業檢核表_架構.md`）本 run 擱置不動、不提交；§4 驗收報告寫入 `docs/research/` 但不提交。
