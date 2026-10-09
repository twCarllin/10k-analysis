# Spec：金控（fh）三表 schema、CAMELS 指標集、年報錨點、FY 損益與 TTM、IFRS 17 斷層標記（工作包 E，`tw-equity`）

> run_id：`2026-10-09-tw-equity-fh-schema`。前序：`spec/2026-10-09-tw-equity-statements.md`（三表帳本）、`spec/2026-10-09-tw-equity-metrics.md`（指標登錄表）、`spec/2026-10-09-tw-equity-fs-generalize.md`（三表泛化，下稱「泛化 Spec」）、`spec/2026-10-09-tw-equity-period-model.md`（期間模型＋FY 損益＋TTM，下稱「期間 Spec」）。研究依據：`docs/research/2026-10-09_00_summary.md` §2.2 第 5 點、§3、§4 工作包 E。
> 本 Spec 自足：不依賴對話。

---

## 0. 定位

### 0.1 目標
`tw_equity_inputs/` 中 `group: "fh"` 的金控公司，目前走一般產業的解析與指標流程：科目幾乎全部對照不到、30 項指標全部是 None、批次摘要把金控列為「未支援」（`runtime/tw_equity/batch_summary.py:13` `UNSUPPORTED_GROUPS`）。本 run 為金控建立一套獨立 schema，讓金控的三表、指標、FY 損益、TTM 能以可追溯數字輸出。

### 0.2 範圍（使用者 2026-10-09 裁示）
- **公司**：2881、2882、2885、2886、2887、2891（6 家；都有 `tw_equity_inputs/<t>.json`、`tw_report/<t>_2025年報.pdf`、`tw_report/<t>_2026Q2財報.pdf`）。
- **2884 不納入**（只有半年報、沒有年報與輸入檔）。
- 納入的工作：
  1. 金控三表 canonical key ＋ 勾稽（§2）。
  2. 金控指標集（CAMELS 分類，三表可算的指標 ＋ 附註抽取）（§3、§4）。
  3. 年報章節錨點（金控年報準則章名）（§5）。
  4. 年報 FY 損益（合併或個體）＋ 金控 TTM（§6）。
  5. IFRS 17 斷層標記（§7）。
  6. 批次輸出與跨公司摘要支援 fh（§8）。
- **不打外部 API**（無 OCR、無 LLM）。全部確定性計算。

### 0.3 驗收門檻（使用者裁示）
- **6 家半年報的金控勾稽（§2.4）全部 `passed=True`**（每項 × current／prior 兩期）。未過者在驗收輸出逐家逐項寫根因；任一未過＝驗收不過，交使用者裁決。
- 工業股不退步：泛化 Spec 驗收 **26/29** 不變（`runtime/tw_equity/fs_acceptance.py`）；期間 Spec FY 損益驗收 **27/30** 不變（`runtime/tw_equity/fy_acceptance.py`）。
- 6 家年報的 `ar_business`、`ar_mdna`、`ar_fin_performance` 錨點全部非 None（§5）。
- 6 家 FY 損益可用（§6.4 的 `usable=True`），TTM 狀態符合 §6.5 表。
- 逾放比／覆蓋率 6 家的 115.6.30 值全部抽到，且等於 §4.2 表列的原文數字。
- 6 家金控 bridge 殘差絕對值 ≤ 2 仟元，無例外（使用者 2026-10-09 裁示）。
- 既有測試全部通過（`./.venv/bin/python -m pytest -q`）；只准改 `tests/tw_equity/test_batch.py` 的 SCHEMA_VERSION 斷言與 `tests/tw_equity/test_batch_summary.py` 的「fh 未支援」斷言（使用者 2026-10-09 同意）。

### 0.4 實測事實（2026-10-09，以既有快取 `data/cache/tw_equity/*.json` 經 `pdf_doc.from_json` 讀出；頁碼為 PDF 頁 `Page.number`）

**F1 科目代碼為 5 位數**：金控 BS／IS 列首是 5 位數代碼（`11000 現金及約當現金`、`41000 利息收入`、`51000 減：利息費用`、`49800 手續費及佣金淨收益`）。現行 `_CODE_STD_RE = ^[0-9][0-9Xx]{3}$`（`statements.py:167`）只認 4 位數。現況 2881 BS 只解析出 7 列、IS 13 列。CF 列無代碼，可解析。

**F2 三表頁碼**（H1 報告）：2881 BS p8、IS p9–10、CF p11–12；2886 BS p10–11、IS p12–13、CF p15–16。2881 BS 為左右並排，每邊 4 欄（115.6.30／114.12.31／114.6.30／114.1.1，標「(重編後)」）；2886 BS 4 欄。

**F3 BS 科目**（2886）：現金及約當現金－淨額、存放央行及拆借金融同業、透過損益按公允價值衡量之金融資產、透過其他綜合損益按公允價值衡量之金融資產、按攤銷後成本衡量之債務工具投資、附賣回票券及債券投資、應收款項－淨額、本期所得稅資產、貼現及放款－淨額、保險合約資產及再保險合約資產、採用權益法之投資、其他金融資產、投資性不動產、不動產及設備、使用權資產、無形資產、遞延所得稅資產、其他資產、資產總計；央行及金融同業存款、央行及同業融資、透過損益按公允價值衡量之金融負債、附買回票券及債券負債、應付商業本票、應付款項、本期所得稅負債、存款及匯款、應付債券、其他借款、負債準備、其他金融負債、保險合約負債及再保險合約負債、租賃負債、遞延所得稅負債、其他負債、負債總計、普通股股本、資本公積、法定盈餘公積、特別盈餘公積、未分配盈餘、其他權益、權益總計、負債及權益總計。2881 另有：特別股股本、待分配股票股利、股本合計、保留盈餘合計、歸屬於母公司業主之權益總計、非控制權益、待出售資產、與待出售資產直接相關之負債。

**F4 IS 結構**（2881、2886 相同）：41000 利息收入、51000 減：利息費用 → 利息淨收益；利息以外淨收益：49800 手續費及佣金淨收益、49815 保險服務結果、49820 透過損益按公允價值衡量之金融資產及負債損益、49825 投資性不動產損益、49835 透過其他綜合損益按公允價值衡量之金融資產已實現損益、49850 除列按攤銷後成本衡量之金融資產損益、49870 兌換損益、49880 資產減損、49890 權益法份額、49816 分離帳戶保險商品資產淨損益（僅 2881）、49817 保險財務收益或費用、49818 所持有之再保險合約財務收益或費用、49900 其他利息以外淨損益 → 淨收益 → 58100 呆帳費用、承諾及保證責任準備提存 → 58200 保險其他營業成本 → 營業費用：58501 員工福利費用、58503 折舊及攤銷費用、58599 其他業務及管理費用 → 營業費用合計（2886 寫「營業費用小計」）→ 61000 繼續營業單位稅前淨利（2881 寫「稅前損益」）→ 61003 所得稅費用 → 69000 本期稅後淨利 → 69500 以後為其他綜合損益。

**F5 CF 科目**（2881）：呆帳費用提列數、外匯價格變動準備、保險特別準備及其他準備本期淨變動、保證責任準備淨變動、存放央行及拆借金融同業增減、附賣回票券及債券投資增加、貼現及放款增加、保險合約資產增減、央行及銀行同業存款增減、附買回票券及債券負債增加、存款及匯款增加、保險合約負債增加、其他金融負債增減，以及多項處分投資利益。

**F6 現況批次結果**（`data/output/batch/full/`）：6 家 status `ok`、basis `H1`；勾稽 passed／None：2881 2／20、2882 2／20、2885 6／16、2886 8／14、2887 4／18、2891 2／20；n_unmapped 48–79；30 項指標全 None；`fy_income_usable` None。

**F7 附註：集團資本適足率**（H1 報告）：115.6.30 **6 家皆未揭露**（依主管機關函令延後補正）。可得的最新期：

| 代號 | 頁 | 可得期 | 原文 |
|---|---|---|---|
| 2881 | p354 | 114.6.30 | `集團資本適足比率 139.13`（單位列「單位：新台幣千元；％」） |
| 2882 | p280 | 114.6.30 | `集團資本適足比率 120.22%` |
| 2885 | p212 | 114.6.30 | `集團資本適足比率 130.70%` |
| 2886 | p160 | 114.6.30 | `(C)=(A)÷(B) (C) 133.83%`（p159 的 115.6.30 表金額欄全填「註」） |
| 2887 | p220 | 無表 | 只有敘述「預計於民國115年9月30日前完成補正」 |
| 2891 | p118 | 114.12.31 ＆ 114.6.30 | `125.07 %`；`115.79 %` |

比率列用字為「集團資本適足**比**率」。各家小節標題：2881、2882「集團資本適足率」；2885「(四)資本適足性」；2886「(三)資本適足性」「1.集團資本適足率」；2887「(3) 資本適足率」；2891「(4)集團資本適足率」。銀行 BIS／第一類資本比率／普通股權益比率、保險 RBC：6 家 H1 只出現在敘述文字，**無數字表**。存放比率：6 家 H1 皆無揭露。

**F8 附註：逾放比、備抵呆帳覆蓋率**（銀行子公司，固定列名 `放款業務合計`；欄序：逾期放款、放款總額、逾放比率、備抵呆帳、備抵呆帳覆蓋率）：

| 代號 | 頁 | 版面 | 115.6.30 原文（數據列） |
|---|---|---|---|
| 2881 | p290（115.6.30）、p291（114.6.30） | 每期一張表；數字後無 `%` | `放款業務合計 3,120,108 2,732,901,311 0.11 34,720,067 1,112.78` |
| 2882 | p285 | 兩期並排同一列 | `放款業務合計 $ 4,435,753 $ 3,061,912,387 0.14% $ 48,813,409 1100.45% $ 3,636,751 …0.14% … 1200.00%` |
| 2885 | p247 | 兩期並排 | `放款業務合計 1,713,246 1,572,996,203 0.11% 18,697,751 1,091.36% 1,281,897 … 0.10% … 1,282.23%` |
| 2886 | p114（115.6.30）、p115（114.6.30） | 每期一張表 | `放款業務合計 $ 5,226,350 $ 2,678,105,416 0.20% $ 42,497,659 813.14%` |
| 2887 | p242（台新銀行，兩期並排）、p259（臺灣新光商銀，僅 115.6.30） | 兩家銀行 | 台新：`放款業務合計 2,711,606 2,018,299,557 0.13% 25,018,211 922.63% 2,454,542 … 0.14% … 921.53%`；新光：`放款業務合計 $1,203,600 $943,395,001 0.13% $12,011,589 997.97%` |
| 2891 | p95 | 兩期上下分開；`%` 前有空格 | `放款業務合計 25,574,796 4,734,430,668 0.54 % 71,730,207 280.47 %`（114.6.30：`0.48 % … 324.16 %`） |

共同小節標題含「資產品質」（例：「逾期放款及逾期帳款資產品質」「放款資產品質」「ii. 資產品質」）。

**F9 年報 FY 損益表**：金控年報**沒有**五年簡明損益表與五年財務分析表；只有「伍、財務狀況及財務績效之檢討分析與風險管理事項」章「財務績效」節的兩年比較表：

| 代號 | 頁 | 範圍 | 欄序／特徵 |
|---|---|---|---|
| 2881 | p243 | 合併（「(1) 合併綜合損益表」） | 欄名西元 `2024年度 2025年度`，**舊年在前**；費用為正數 |
| 2885 | p266 | 合併（「(一) 本公司其及子公司合併綜合損益表」；同頁另有個體表） | 114 在前、113 在後；費用加括號 |
| 2886 | p120 | 合併（「二、財務績效」） | 114 在前、113 在後；有「淨利歸屬於母公司業主」列 |
| 2882 | p231 | **只有個體** | 只有 `淨收益／費用及損失／稅前損益／稅後純益` 四列 |
| 2887 | p242 | **只有個體**（「個體財務績效」） | 列 `採權益法認列之投資損益 … 本期(損)益` |
| 2891 | p160 | **只有個體** | 列 `採用權益法之關聯企業及合資收益之份額 … 稅後淨利` |

2881 p243 原文：
```
項目 2024年度 2025年度 增減金額 變動(%)
利息淨收益 181,744,840 190,389,088 8,644,248 4.76%
利息以外淨收益 165,718,655 190,917,047 25,198,392 15.21%
淨收益 347,463,495 381,306,135 33,842,640 9.74%
呆帳費用、承諾及保證責任準備提存 12,926,807 11,514,179 (1,412,628) (10.93%)
保險負債準備淨變動 68,382,783 135,253,603 ...
營業費用 93,846,014 97,475,702 ...
繼續營業單位稅前淨利 172,307,891 137,062,651 ...
所得稅(費用)利益 (21,446,852) (16,080,865) ...
本期淨利(淨損) 150,861,039 120,981,786 ...
```
年報損益表無每股盈餘列。

**F10 年報章名**：2882、2885、2887、2891 用「壹…陸」（2887、2891 另有「柒」）；2881 用阿拉伯數字（`1. 致股東報告書`…`4. 營運概況`、`4.1 本公司營運概況`、`5. 財務狀況及財務績效檢討分析與風險管理事項`、`5.2 財務績效`、`6. 特別記載事項`；注意「檢討分析」前無「之」）；2886 目錄無編號，章名「財務狀況及財務績效之檢討分析與風險管理」（無「事項」）。章名起始 PDF 頁：2882 肆 159、伍 230、陸 253；2885 肆 168、伍 264、陸 282；2887 伍 240、陸 278；2891 肆 95、伍 160、陸 178；2881 4. 157、5. 240、6. 267；2886 伍 118、特別記載事項 151。現況：2881 `ar_business`／`ar_mdna`／`ar_fin_performance` 皆 None；2886 `ar_mdna` None。2886 業務章含「一、業務內容」。

**F11 IFRS 17 出現頁**（H1 報告，去空白後搜「IFRS17」或「國際財務報導準則第17號／第十七號」）：2881 約 21 頁、2882 16 頁、2887 11 頁、2891 1 頁（p5）。IS 含 `保險服務結果` 列者即適用 IFRS 17 的保險業務。

**F12 程式現況**：
- 無任何依 group 分流的邏輯；`inputs.TwEquityInputs` 無 group 欄位；group 只在 `batch.py:85` 讀入輸出記錄。
- `statements.extract_statements(fs, fs_anchors)`（`statements.py:1178`）無 schema 參數；`map_key` 讀模組全域 `CANONICAL_KEYS`；`run_cross_checks` 讀全域 `_CHECK_SPECS`（11 項，容許誤差 2 仟元）。
- `metrics.compute_metrics(ledger, fy_income)`、`compute_bridges`、`compute_ttm` 直接迭代全域 `METRIC_SPECS`（30）／`BRIDGE_SPECS`（8）／`TTM_KEYS`。
- `fy_income.extract_fy_income(ar, ar_anchors, *, roc_year)`：候選頁需 `revenue` 列＋表頭 `{roc_year}年` 與 `{roc_year-1}年`＋營收列後 40 列內 ≥2 列 `_CORE_KEYS`；`_REQUIRED_CURRENT=("revenue","operating_income","pretax_income","net_income")`。
- `tables.extract_tables(ar, ar_anchors, fs, fs_anchors, ps, ps_anchors, *, roc_year, gov_anchors=None)`（`tables.py:1556`）依序呼叫 `extract_statements` → `extract_fy_income` → `compute_metrics`。
- `batch.SCHEMA_VERSION = 1`；`VALUE_KEYS = ("revenue","gross_profit","operating_income","net_income","cfo")`。

### 0.5 不碰的既有檔案
`runtime/tw_credit/**`、`runtime/orchestrator.py`、`runtime/jp_*.py`、`runtime/agent_runner.py`、`runtime/report_writer.py`、`skills/**`、`agents/**`、`main.py`、`runtime/tw_equity/pdf_doc.py`、`runtime/tw_equity/ocr.py`、`runtime/tw_equity/cross_year.py`、`tw_equity_inputs/**`、`tw_report/**`、`docs/research/**`。
允許改：`runtime/tw_equity/statements.py`、`metrics.py`、`fy_income.py`、`doc_anchor.py`、`sections.py`（僅在錨點 key 需要時）、`tables.py`（僅 `extract_tables` 傳遞 group 與附註抽取接線）、`inputs.py`（只加 optional `group` 欄位）、`tw_pipeline.py`（只傳遞 group）、`batch.py`、`batch_summary.py`、`report.py`（只限附錄顯示 fh 指標與 IFRS 17 標記）；新檔 `runtime/tw_equity/fh_schema.py`、`runtime/tw_equity/fh_notes.py`、`runtime/tw_equity/fh_acceptance.py`；`tests/tw_equity/**`、`tests/fixtures/tw_equity/**`。

---

## 1. 分流原則（group）

- `group` 值域沿用輸入檔：`"fh"` 為金控；其他值（含 None）一律走既有工業流程，**行為與本 run 前完全相同**。
- `inputs.TwEquityInputs` 新增 optional `group: str | None`（讀輸入檔 `group`，缺→None）；既有欄位與驗證不變。
- `tables.extract_tables(..., group: str | None = None)` 新增 keyword 參數，往下傳 `extract_statements`、`extract_fy_income`、`compute_metrics`、附註抽取。`tw_pipeline` 與 `batch` 傳入 `inputs.group`。
- 金控 schema（科目、區段標題、勾稽、指標、bridge、TTM key）集中在新檔 `runtime/tw_equity/fh_schema.py`；工業 schema 留在原檔原名（`CANONICAL_KEYS`、`_CHECK_SPECS`、`METRIC_SPECS`、`BRIDGE_SPECS`、`TTM_KEYS` 名稱與內容不變，既有 import 不壞）。
- **5 位數代碼剝除只在 group == "fh" 時啟用**（工業股的 5 位數可能是金額，不可誤剝）。

---

## 2. 金控三表（`statements.py` ＋ `fh_schema.py`）

### 2.1 解析
- 金控列首代碼：`^\d{5}$`（含黏著於中文前的 `\d{5}`）剝除為 `StatementRow.code`，不當金額。
- `減：` 前綴（`51000 減：利息費用`）在對照前移除（label 保留原文）。
- BS 4 欄（115.6.30／114.12.31／114.6.30／114.1.1）與 `(重編後)` 表頭變體：期間偵測沿用泛化 Spec §2.1；`(重編後)` 不影響期間判定。current／prior 選欄沿用泛化 Spec §1.3（BS prior＝上年度末 12-31）。
- 左右並排 BS（2881）：沿用泛化 Spec 的並排頁處理；金控右半代碼為 5 位數（`2xxxx`／`3xxxx`），並排判定需支援。

### 2.2 canonical key（`FH_CANONICAL_KEYS`，鍵為 `"bs"`／`"is"`／`"cf"`）
key 名稱為**最小必要集**；別名以 §0.4 F3–F5 原文為來源，實作時從 6 家實際 unmapped 清單補齊。

- **BS**：`cash`（現金及約當現金(－淨額)）、`due_from_central_bank`（存放央行及拆借金融同業）、`fvtpl_assets`、`fvoci_assets`、`amortized_cost_assets`、`reverse_repo`（附賣回票券及債券投資）、`receivables`（應收款項－淨額）、`loans_net`（貼現及放款－淨額）、`insurance_contract_assets`、`equity_method_investments`、`investment_property`、`ppe`、`total_assets`（資產總計）；`due_to_central_bank`（央行及金融同業存款）、`fvtpl_liabilities`、`repo`（附買回票券及債券負債）、`commercial_paper`、`payables`、`deposits`（存款及匯款）、`bonds_payable`、`other_borrowings`、`provisions`、`insurance_contract_liabilities`（保險合約負債及再保險合約負債）、`total_liabilities`（負債總計）、`share_capital`、`capital_surplus`、`retained_earnings`、`equity_parent`（歸屬於母公司業主之權益(總計)）、`nci`、`total_equity`（權益總計）、`total_liabilities_and_equity`（負債及權益總計）。
- **IS**：`interest_income`、`interest_expense`、`net_interest_income`（利息淨收益）、`fee_income_net`（手續費及佣金淨收益）、`insurance_service_result`（保險服務結果）、`fvtpl_gain`、`fx_gain`、`equity_method_share`、`non_interest_income`（利息以外淨收益(合計)）、`net_revenue`（淨收益）、`provision`（呆帳費用、承諾及保證責任準備提存）、`insurance_other_cost`（保險其他營業成本）、`insurance_reserve_change`（保險負債準備淨變動；年報 IFRS 4 格式用）、`employee_benefits`、`depreciation_amortization`、`other_ga`、`total_opex`（營業費用合計／小計）、`pretax_income`（繼續營業單位稅前淨利、稅前損益）、`income_tax`（所得稅費用／(費用)利益）、`net_income`（本期稅後淨利、本期淨利）、`net_income_parent`、`net_income_nci`（淨利歸屬於區段，沿用 `_IS_SPLIT_LABELS` 機制）、`eps_basic`。
- **CF**：沿用工業 CF 的 `cfo`、`cfi`、`cff`、`fx_effect`、`net_change_in_cash`、`cash_beginning`、`cash_ending`、`cash_per_bs_in_cf`、`pretax_income_cf`；另加 `provision_cf`（呆帳費用提列數）、`loans_change`（貼現及放款增加／減少）、`deposits_change`（存款及匯款增加／減少）。金控 CF 期末現金與 BS 現金的差異（含「符合 IAS 7 定義之存放央行及拆借金融同業」等調節列）由 `cash_per_bs_in_cf` 或對應調節列處理。

### 2.3 區段標題（`FH_SECTION_HEADERS`）
至少含：資產、負債、權益、利息以外淨收益、營業費用、其他綜合損益、不重分類至損益之項目、後續可能重分類至損益之項目、淨利歸屬於：、綜合損益總額歸屬於：，以及 CF 的營業／投資／籌資活動之現金流量與調整項目區段標題。

### 2.4 金控勾稽（`FH_CHECK_SPECS`；每項 × current／prior；容許誤差沿用 2 仟元）

| name | 等式 |
|---|---|
| `bs_assets_eq_liab_equity` | total_assets = total_liabilities_and_equity |
| `bs_liab_equity_sum` | total_liabilities + total_equity = total_liabilities_and_equity |
| `is_net_interest` | interest_income − \|interest_expense\| = net_interest_income |
| `is_net_revenue` | net_interest_income + non_interest_income = net_revenue |
| `is_pretax` | net_revenue − \|provision\| ＋ insurance_other_cost（依報表原號） − \|total_opex\| = pretax_income |
| `is_net_income` | pretax_income − 所得稅（符號規則沿用工業 `income_tax` 處理） = net_income |
| `cf_net_change` | cfo + cfi + cff + fx_effect = net_change_in_cash |
| `cf_ending` | cash_beginning + net_change_in_cash = cash_ending |
| `cf_pretax_eq_is` | pretax_income_cf = pretax_income |

- 費用類（interest_expense、provision、total_opex）不論報表印正數或括號，一律取絕對值後相減。
- `insurance_other_cost`（保險其他營業成本）**依報表原號相加**，不取絕對值：H1 報告以括號（負值）表示成本、正值表示淨回升（實測 2881 114H1 +30,817,980、2885 +447,484／+6,246,652、2891 114H1 +6,468,400）。主 flow 裁決 2026-10-09（item 1.5 實測）。
- **選填項目規則**：`insurance_other_cost` 為選填——該公司 IS 無此列（非保險金控）時以 0 計；其他項目缺列 → `passed=None`（不得以 0 代入）。
- `is_net_revenue` 若公司未列 `non_interest_income` 合計列，以 F4 列出的利息以外各項加總代替（實作需記於 `parse_warnings`）。
- 「CF 期末現金＝BS 現金」不列入金控勾稽（金控 CF 現金定義含存放央行部分，與 BS 現金不同口徑）。

### 2.5 帳本輸出
- `StatementLedger` 新增 `schema: str`（`"industrial"`／`"fh"`），`to_dict()` 輸出；其他鍵不變。
- 工業股的 `rows`、`checks`、`unmapped_labels` 與本 run 前逐值相同（回歸測試鎖定 3653 年度財報與至少 2 家半年報）。

---

## 3. 金控指標集（`fh_schema.FH_METRIC_SPECS`，沿用 `MetricSpec` 結構）

- `compute_metrics(ledger, fy_income, *, group=None, notes=None)`：group == "fh" → 用 `FH_METRIC_SPECS`、`FH_BRIDGE_SPECS`、金控 TTM（§6.5）；否則行為不變。
- 金控**不算** 30 項工業指標與 8 組工業 bridge（不輸出 None 佔位）。
- H1 期間的流量比率**不年化**，與工業股一致；指標名稱註明「H1 未年化」。

| CAMELS | key | 名稱 | 公式 | 單位 |
|---|---|---|---|---|
| C | `equity_to_assets` | 權益／資產 | total_equity ÷ total_assets | % |
| C | `group_car` | 集團資本適足率 | 附註（§4.1） | % |
| A | `npl_ratio` | 逾放比 | 附註（§4.2） | % |
| A | `coverage_ratio` | 備抵呆帳覆蓋率 | 附註（§4.2） | % |
| A | `credit_cost` | 信用成本 | \|provision\| ÷ loans_net | % |
| M | `cost_income_ratio` | 成本收入比 | \|total_opex\| ÷ net_revenue | % |
| E | `roa` | ROA（期末，H1 未年化） | net_income ÷ total_assets | % |
| E | `roe` | ROE（期末，H1 未年化） | net_income ÷ total_equity | % |
| E | `nii_share` | 利息淨收益占淨收益 | net_interest_income ÷ net_revenue | % |
| E | `fee_share` | 手續費淨收益占淨收益 | fee_income_net ÷ net_revenue | % |
| E | `pretax_margin` | 稅前淨利率 | pretax_income ÷ net_revenue | % |
| L | `loan_to_deposit` | 放款／存款（合併資產負債表口徑，非法定存放比） | loans_net ÷ deposits | % |
| L | `liquid_to_assets` | 流動性資產／資產 | (cash + due_from_central_bank) ÷ total_assets | % |

- ROA／ROE 用期末值，不做平均：沿用 `metrics.py` 既有規則「所有指標一律期末值（不做平均）」（`metrics.py:4`）。主 flow 裁決 2026-10-09（原文「沿用工業平均規則」與程式事實矛盾）。
- 附註來源的指標（`group_car`、`npl_ratio`、`coverage_ratio`）在 `MetricsPack` 的每期值旁輸出 `source`（`{"doc": "fs", "page": int, "period": "115-06-30", "entity": "<銀行名或集團>", "stale": bool}`）。
- `source.reason`（主 flow 裁決 2026-10-09，Task 3 審查）：值為 None 時寫原因（「未揭露（延後補正）」「無資產品質附註」「附註無對應期間」「附註抽取失敗」）；值存在但附註期別與帳本 prior 期不同時寫「附註期別與帳本 prior 期不同」。因此 `reason` 存在**不代表**無值。npl／coverage 的 prior 取「附註中早於 current 的最新一期」；`group_car` 只取最新可得期，prior 為 None。
- **金控 bridge**（`FH_BRIDGE_SPECS`，1 組）：`net_income` 變動（current vs prior）＝ Δnet_interest_income ＋ Δnon_interest_income − Δ\|provision\| ＋ Δinsurance_other_cost（原號） − Δ\|total_opex\| − Δ所得稅；沿用 `_build_bridge` 的輸出格式（top_drivers）。

---

## 4. 附註抽取（新檔 `runtime/tw_equity/fh_notes.py`）

`extract_fh_notes(fs: PdfDoc) -> FhNotes`，只在 group == "fh" 時呼叫。純規則解析，不用 LLM。

### 4.1 集團資本適足率
- 搜尋含「集團資本適足比率」或「集團資本適足率」的數據列（去空白後比對），取該列最後一個百分比數字（容許 `%` 前有空格、無 `%`）。
- 期間：取該表表頭／小節標題中的日期（民國年，`115.6.30`、`114年6月30日` 等）；115.6.30 表若金額欄為「註」或無數字 → 該期視為未揭露。
- 輸出：最新可得期的值＋期間＋頁碼＋`stale=True`（期間早於 H1 報告 BS current 期間時）。無任何可得期（2887）→ None，`reason="未揭露（延後補正）"`。
- 期望值（驗收用）：2881 139.13（114-06-30）、2882 120.22（114-06-30）、2885 130.70（114-06-30）、2886 133.83（114-06-30）、2887 None、2891 125.07（114-12-31）。

### 4.2 逾放比、備抵呆帳覆蓋率
- 定位：含「資產品質」小節標題的頁，找列名 `放款業務合計` 的數據列。
- 一列兩期並排（2882、2885、2887 台新）→ 前 5 個數字為第一期、後 5 個為第二期，期間依表頭日期順序。每期一張表（2881、2886）或上下分開（2891）→ 依該表表頭日期。
- 數值容許：`$` 前綴、千分位、`%` 有／無、`%` 前空格。
- 多家銀行（2887）→ 每家各一筆（entity 取小節標題中的銀行名）；指標主值取**放款總額最大**的銀行，其他銀行列在 `entities` 明細。
- 期望值（115.6.30 主值；驗收用）：

| 代號 | npl_ratio | coverage_ratio |
|---|---|---|
| 2881 | 0.11 | 1112.78 |
| 2882 | 0.14 | 1100.45 |
| 2885 | 0.11 | 1091.36 |
| 2886 | 0.20 | 813.14 |
| 2887 | 0.13（台新） | 922.63（台新） |
| 2891 | 0.54 | 280.47 |

- 114.6.30 期有揭露者一併輸出（prior）；2887 新光商銀僅 115.6.30。

### 4.3 不抽取
銀行 BIS／第一類資本比率／普通股權益比率、保險 RBC、法定存放比——H1 報告無數字表（F7）。`FhNotes.unavailable` 列出這些項目與原因，報告與批次輸出顯示「不可得」。

---

## 5. 年報章節錨點（`doc_anchor.py`）

- 現有 key 不變，補金控章名關鍵字（只增不改既有關鍵字）：
  - `ar_business`：補「營運概況」型（2881 `4.1 本公司營運概況`；壹–陸型「肆、營運概況」後的「一、業務內容」已存在者不受影響）。
  - `ar_mdna`：補「財務狀況及財務績效檢討分析」（無「之」）、「財務狀況及財務績效之檢討分析與風險管理」。
  - `ar_fin_performance`：補「5.2 財務績效」型（阿拉伯數字編號）。
- 驗收：6 家年報 `ar_business`、`ar_mdna`、`ar_fin_performance` 非 None，起頁落在 F10 對應章內；工業股既有錨點測試全過。

---

## 6. 年報 FY 損益與 TTM（`fy_income.py`、`metrics.py`）

### 6.1 呼叫
`extract_fy_income(ar, ar_anchors, *, roc_year, group=None)`：group == "fh" → 走金控路徑（§6.2–6.4）；否則行為不變。

### 6.2 金控候選頁
- 優先 `ar_fin_performance`／`ar_mdna` 錨點範圍。
- 表頭需同時出現本年與上年標記：民國 `{roc_year}年(度)` 與 `{roc_year-1}年(度)`，**或西元** `{roc_year+1911}年(度)` 與 `{roc_year+1910}年(度)`（2881）。欄序依標記位置判定（2881 舊年在前）。
- 合併表優先：頁內或表題含「合併」者優先；同頁有合併與個體兩表（2885）→ 只取合併表的列。
- 找不到合併表 → 取個體表（表題含「個體」，或列含「採權益法認列之投資損益」「採用權益法之關聯企業及合資收益之份額」）。

### 6.3 列對照
- 合併表：用 `FH_CANONICAL_KEYS["is"]`（含 `insurance_reserve_change`）。
- 個體表：只對照淨利列——`稅後純益`、`本期(損)益`、`稅後淨利`、`本期淨利` → `net_income_parent`；其他列保留原文不對照。

### 6.4 輸出與可用性
- `FyIncome` 新增 `scope: "consolidated" | "parent_only"`、`schema: "industrial" | "fh"`；`to_dict()` 輸出。
- 金控 `usable` 條件：合併 → 本期 `net_revenue`、`pretax_income`、`net_income` 皆有值；個體 → 本期 `net_income_parent` 有值。
- 金控 FY 勾稽：合併表跑 `is_net_income`（pretax − 所得稅 = net_income）；`is_pretax` 在年報格式下為 net_revenue − \|provision\| − \|insurance_reserve_change\| − \|total_opex\| = pretax_income（IFRS 4 格式）。
- 期望：2881、2885、2886 → consolidated、usable；2882、2887、2891 → parent_only、usable。

### 6.5 金控 TTM（`compute_ttm`）
- 公式沿用期間 Spec：TTM = FY + H1 current − H1 prior；前提條件（basis H1、單位仟元、年度對應）不變。
- consolidated：TTM key＝`net_interest_income`、`non_interest_income`、`net_revenue`、`provision`、`total_opex`、`pretax_income`、`income_tax`、`net_income`、`net_income_parent`（FY 缺的 key → 該 key TTM 為 None，其他照算）。
- parent_only：只算 `net_income_parent`（個體淨利＝合併的歸屬母公司業主淨利）；其他 key 不輸出。`ttm.scope="parent_only"`。
- 適用 IFRS 17 者（§7）：TTM 照算，`ttm.comparability = "ifrs17_break"`，並附說明「FY2025 為 IFRS 4、2026H1 與 2025H1 為 IFRS 17（重編），TTM 混用兩種準則」。
- 期望 TTM 狀態：2881、2885、2886 → `ok`（consolidated）；2882、2887、2891 → `ok`（parent_only，只有 net_income_parent）。

---

## 7. IFRS 17 斷層標記

- 判定（確定性）：H1 帳本 IS 有 `insurance_service_result` 列 → `ifrs17_break=True`；否則 False。輸出 `ifrs17_evidence`：`{"rule": "is_has_insurance_service_result", "label": <原文列名>}`。
- 影響：
  - TTM 加 `comparability="ifrs17_break"`（§6.5）。
  - 指標的 prior 欄：H1 報告的上年同期已依 IFRS 17 重編，可比；不另標記。
  - FY（IFRS 4）與 H1 的跨期比較在報告與批次摘要加註。
- 期望：6 家中有保險子公司者（至少 2881、2882、2887、2891）為 True；實測值寫入驗收輸出。

---

## 8. 批次輸出與跨公司摘要（`batch.py`、`batch_summary.py`、`report.py`）

### 8.1 每家 JSON（`batch.py`）
- `SCHEMA_VERSION = 2`。工業股記錄的既有鍵與值不變；新增頂層鍵 `schema`（`"industrial"`／`"fh"`）與 `ifrs17_break`（工業股為 None）。
- 金控記錄：`values` 改用 `FH_VALUE_KEYS = ("net_interest_income","non_interest_income","net_revenue","provision","total_opex","pretax_income","net_income","net_income_parent","total_assets","total_equity","loans_net","deposits")`；`metrics` 為 §3 的 13 項（含附註 source）；`ttm` 增 `scope`、`comparability`；`bridges` 為 §3 的金控 bridge；新增 `fh_notes`（§4 輸出，含 unavailable）。另有 `fh_notes_error`（附註抽取例外時為 `"<類型>: <訊息>"`，成功為 None；只在 fh 記錄出現。主 flow 裁決 2026-10-09，Task 5 審查）。
- `manifest` 的欄位不變。

### 8.2 跨公司摘要（`batch_summary.py`）
- 移除 fh 的「未支援」排除（`UNSUPPORTED_GROUPS` 不再含 fh）。
- 工業排名表與紅旗不變，且**不含金控**。
- 新增金控排名表 `FH_RANK_COLUMNS`：淨收益（百萬元）、ROE、ROA、成本收入比、信用成本、逾放比、覆蓋率、權益／資產、放款／存款、集團 CAR（標註期間）、TTM 淨利或 TTM 歸母淨利（標註 scope）、IFRS 17 標記。
- summary.json 新增 `fh_ranking`；summary.md／summary.html 新增「金控」一節。金控不套用工業紅旗 R1–R8／Q1。

### 8.3 報告（`report.py`）
- 附錄 E 遇 `schema == "fh"`：列出 §3 指標（含附註 source 與 stale 註記）、金控 bridge、IFRS 17 標記、§4.3 不可得清單。工業股附錄 E 輸出不變。
- 只做本地渲染驗證，不跑真實 e2e／不打 API。

---

## 9. 驗收工具（新檔 `runtime/tw_equity/fh_acceptance.py`）

- `python -m runtime.tw_equity.fh_acceptance`：對 6 家跑 H1 三表＋附註＋年報錨點＋FY 損益＋TTM＋IFRS 17，逐家輸出：勾稽通過數／總數與未過項、n_unmapped、附註值 vs §4 期望值、錨點起頁、FY scope／usable、TTM 狀態、ifrs17_break；最後一行總結 `PASS n/6`。
- 只讀本地快取與 PDF，不打 API；有 `--tickers` 參數。
- 驗收結果（輸出全文）貼入 task 檔對應 item 的完成證據。

---

## 10. 開放問題
（無；§0.2、§4、§6.5 的範圍已由使用者 2026-10-09 裁示：附註抽取＝逾放比＋覆蓋率＋集團 CAR 最新可得期；個體年報公司做歸母淨利 TTM；2884 不納入；驗收＝6 家金控勾稽全過。）
