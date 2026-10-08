# Spec：台股財報 Phase 2-1 合併財報三表逐列解析＋科目對照＋勾稽（`tw-equity`）

> run_id：`2026-10-09-tw-equity-statements`。前序：`spec/2026-10-08-tw-equity-phase-1b2.md`（1B-2）、run `2026-10-08-tw-equity-rotated-pages`（橫向頁轉正、取消截斷）。
> 本 Spec 自足：不依賴對話。上位目標（使用者 2026-10-08 裁示）：建立「會計問答」能力——問「FCF 多少」「影響 FCF 最多的是什麼」要能以可追溯的數字回答。分四階段：**本 run＝階段 1（事實帳本）**；階段 2 指標與歸因引擎、階段 3 問答 skill＋`--ask` CLI、階段 4 年報 C 項章節接入，皆不在本 run。

---

## 0. 定位與前提

### 0.1 範圍
合併財報的三張主表（合併資產負債表、合併綜合損益表、合併現金流量表）**逐列**解析成標準化帳本（`StatementLedger`）：每列含科目原文、標準代號（`key`）、本期／上期金額、百分比（BS／IS）、附註編號、來源頁與列號。帳本做確定性勾稽（資產＝負債＋權益等），結果併入 `TablesBundle`，隨 `tables_json` 送 skill、隨 `raw.json` 落地，報告加附錄 D。無 LLM。

### 0.2 實測事實（2026-10-09，3653 之 114 年度合併財報 `tw_report/3653_2025Q4合併財報.pdf`）

| 項目 | 事實 | 處置 |
|---|---|---|
| 列通道（`Page.lines`，fitz words 分群） | 三表每列格式乾淨：`科目 [附註] 金額 [%] 金額 [%]`。例：`現金及約當現金 六(一) $ 9,134,067 33 $ 2,267,253 12`、`營業成本 六(五)(二十一)` ＋ 續行 `及七 ( 11,841,587 ) ( 58) ( 8,912,721) ( 62 )`、CF：`折舊費用 六(七)(八)` ＋ 續行 `(二十一) 629,171 576,411` | 列通道解析；附註 token 剝除；續行合併（§2.1） |
| 金額寫法 | 千分位；負數為 `( 11,841,587 )` 或 `($ 154,025 )`；零／無值為 `-`；首列有 `$` | 重用 `tables.line_amounts`／`_norm_line`／`parse_amount`（已處理括號負數、`$`、`-`→None） |
| 期間標題列 | BS：`114 年 12 月 31 日 113 年 12 月 31 日`；IS：`114 年 度 113 年 度`；CF：`附註 1 1 4 年 度 1 1 3 年 度`（字元間有空格） | NFKC＋去空白後以 `(\d{2,3})年` 取兩個民國年（§2.1） |
| 單位列 | `單位：新台幣仟元`（IS 另有 `(除每股盈餘為新台幣元外)`） | 記 `unit`；EPS 列不換算 |
| 錨點頁範圍 | `fs_bs`=10–11、`fs_is`=12–13（p13 是合併權益變動表）、`fs_cf`=14–28（p16 起為附註） | 以頁首 3 列是否含表名（`資產負債表`／`綜合損益表`／`現金流量表`，NFKC 去空白比對）篩頁，首個不符頁即停（§2.2） |
| 群組標題列（無金額） | BS：`資產`、`負債`（2026-10-09 reviewer 🟡3 補：標題後直接接科目時不得吞列）、`流動資產`、`非流動資產`、`流動負債`、`非流動負債`、`權益`、`歸屬於母公司業主之權益`、`股本 六(十四)`、`資本公積 六(十五)`、`保留盈餘 六(十六)`、`其他權益 六(十七)`；IS：`營業費用 六(二十一)及七`、`營業外收入及支出`、`其他綜合損益`、`不重分類至損益之項目`、`後續可能重分類至損益之項目`、`淨利歸屬於：`、`綜合損益總額歸屬於：`；CF：`營業活動之現金流量`、`調整項目`、`收益費損項目`、`與營業活動相關之資產/負債變動數`、`與營業活動相關之資產之淨變動`、`與營業活動相關之負債之淨變動`、`投資活動之現金流量`、`籌資活動之現金流量` | 群組標題 vs 科目續行的判別規則見 §2.1 |
| 尾列 | `(續 次 頁)`、`~10~`、`後附合併財務報表附註…`、`董事長：…` | 無金額且非群組標題、且下一列無金額或不存在 → 丟棄 |
| 既有 `consolidated_key_lines`（`tables.parse_key_lines_from_lines`，6 個標籤） | 已供 `parent_cost_coverage` 與 skill 使用 | **不改、不移除**；帳本為新增並行資料（階段 2 再決定是否以帳本取代） |
| 既有 fixture `tests/fixtures/tw_equity/fs_3653_pages.json` | 含 p10、11、12、14；缺 p13（權益變動表，用來驗「IS 篩頁在 p13 停」）與 p15（CF 第二頁，投資／籌資活動） | producer `_SELECTED_PAGES` 加 13、15 後重產（§4） |

### 0.3 不碰的既有檔案
`runtime/tw_credit/**`、`runtime/orchestrator.py`、`runtime/jp_*.py`、`runtime/agent_runner.py`、`runtime/report_writer.py`、`skills/**`、`agents/**`、`runtime/eval_runner.py`、`runtime/mock_outputs.json`、`runtime/tw_equity/pdf_doc.py`、`runtime/tw_equity/doc_anchor.py`、`runtime/tw_equity/sections.py`、`runtime/tw_equity/cross_year.py`、`runtime/tw_equity/tw_pipeline.py`、`main.py`。
允許改：新檔 `runtime/tw_equity/statements.py`；`runtime/tw_equity/tables.py`（只加 `TablesBundle.statements` 欄、`to_dict` 一鍵、`extract_tables` 末段接線、`missing_tables` 三個新名稱）；`runtime/tw_equity/report.py`（只加附錄 D 與其 render 函式）；`tests/tw_equity/**`、`tests/fixtures/tw_equity/make_fs_fixture.py`＋`fs_3653_pages.json`；`README.md`（tw-equity 段加一句）。

---

## 1. 資料模型（`runtime/tw_equity/statements.py`，新檔）

```python
@dataclass
class StatementRow:
    statement: str            # "bs" | "is" | "cf"
    section: str | None       # 最近一個群組標題（NFKC 去空白、剝除附註 token，例 `股本`、`淨利歸屬於:`），無則 None（2026-10-09 writer 提問後釐清）
    label: str                # 科目原文（續行已合併、附註 token 已剝除、NFKC、去空白）
    key: str | None           # 標準代號（§3 對照表）；對不到 → None（列保留）
    note: str | None          # 附註 token 原文，如 "六(一)"、"六(四)及七"；無 → None
    current: float | None
    prior: float | None
    current_pct: float | None # 只 bs／is；cf 固定 None
    prior_pct: float | None
    page: int                 # 來源頁（1-indexed）
    line_idx: int             # 該頁 lines 的索引（續行時取首列）
    def to_dict(self) -> dict

@dataclass
class CrossCheck:
    name: str                 # 固定名稱，見 §2.4
    period: str               # "current" | "prior"
    lhs: float | None
    rhs: float | None
    passed: bool | None       # 任一邊 None → None（無法勾稽），不算失敗
    def to_dict(self) -> dict

@dataclass
class StatementLedger:
    unit: str                 # 例 "新台幣仟元"；找不到 → ""
    period_current: str       # 例 "114"（民國年字串）；找不到 → ""
    period_prior: str
    rows: list[StatementRow]
    checks: list[CrossCheck]
    unmapped_labels: list[str]  # key 為 None 的 label（去重、依出現序）
    def get(self, key: str, statement: str | None = None) -> tuple[float | None, float | None]
        # 第一個 key 相符的列 →(current, prior)；無 → (None, None)
    def to_dict(self) -> dict  # 鍵：unit、period_current、period_prior、rows、checks、unmapped_labels、row_counts{"bs":n,"is":n,"cf":n}
```

---

## 2. 解析契約

### 2.1 `parse_statement_lines(lines: list[tuple[int, int, str]], statement: str, *, section_headers: frozenset[str]) -> tuple[list[StatementRow], str, str]`
輸入：`(page, line_idx, text)` 三元組串列（已依頁、列排序）；回傳 `(rows, period_current, period_prior)`。

1. **正規化**：每列 `_norm_line`（`tables._norm_line`：NFKC、括號負數壓平、去 `$`）；比對用字串另去全部空白、`－`／`—`／`–` 統一為 `-`。
2. **期間標題列**：含「年」且去空白後符合 `(\d{2,3})年.*?(\d{2,3})年` 的首列 → `period_current`、`period_prior`（取前兩個民國年）；此列不產 row。
3. **跳過列**：去空白後為空、以 `~` 開頭（頁碼）、含 `(續次頁)`、以 `後附合併財務報表附註` 開頭、以 `董事長` 開頭、公司名列／表名列／日期列／單位列（頁首 5 列內且無金額）。
4. **附註 token**：regex `_NOTE_RE = ^(?:[一二三四五六七八九十]+(?:\([一二三四五六七八九十]+\))+|\([一二三四五六七八九十]+\))(?:及[一二三四五六七八九十]+(?:\([一二三四五六七八九十]+\))*)*$` 比對列內以空白分隔的 token；命中者從 label 移除、串接進 `note`。例：`六(五)(二十一)`、`及七`（續行開頭的「及七」視為 note 片段：允許 token 以 `及` 開頭）、`(二十一)`、`十二(二)`。
5. **金額 token**：對剝除 note 後的尾段呼叫 `line_amounts`。**bs／is**：取到 4 個 → `(current, current_pct, prior, prior_pct)`；取到 2 個 → `(current, None, prior, None)`；取到 3 個 → `(a0, None, a2, None)` 並視為 `-` 佔位遺漏；0 或 1 個 → 本列無金額。**cf**：2 個 → `(current, prior)`；1 個 → `(current, None)`；0 → 無金額。`-` 已由 `line_amounts` 轉 None。
6. **群組標題 vs 續行**（無金額列的判別）：
   - 去 note、去空白後的文字 ∈ `section_headers`（§2.3 三表各自的常數集合，另含 `淨利歸屬於:`／`綜合損益總額歸屬於:` 這類以 `歸屬於` 結尾者）→ 設為 `section`，不產 row；
   - 否則 → **續行前綴**：與下一列合併（label = 本列文字 + 下一列的非 note、非金額文字；`page`／`line_idx` 取本列；note 兩列串接）。最多合併 1 列（與 `parse_key_lines_from_lines` 同）；下一列亦無金額 → 本列丟棄（尾列規則）。
7. **科目列**：有金額的列 → 產 `StatementRow`，`label` 為剝除 note 與金額後的文字（去空白），`key` 由 §3 對照。
8. **百分比列**：IS 的 `( 58)` 為負百分比，照 `line_amounts` 結果存（-58）；不另處理。
9. **（2026-10-09 真實資料補充）** 欄位標題列（去空白後含 `附註金額`，如 `項目 附註 金額 % 金額 %`）→ 跳過；label 之後的**單獨中文數字 token**（`七`、`十一`）視為附註 token；帶此類附註且無金額的備忘列（`重大之期後事項 十一`）→ 直接丟棄、不作續行前綴。

### 2.2 `statement_pages(doc: PdfDoc, rng: PageRange | None, title_kw: str) -> list[int]`
rng 為 None → `[]`。在 `rng.start..rng.end` 內，頁首 3 列（NFKC 去空白）任一含 `title_kw` 的頁為該表頁；自第一個命中頁起連續取，遇第一個不命中頁即停。`title_kw`：bs=`資產負債表`、is=`綜合損益表`、cf=`現金流量表`。3653 預期：bs=[10,11]、is=[12]、cf=[14,15]。

### 2.3 `extract_statements(fs: PdfDoc | None, fs_anchors: dict | None) -> StatementLedger | None`
fs 或 fs_anchors 為 None → None。三表各自 `statement_pages` → 組 `(page, line_idx, text)` → `parse_statement_lines`。三表皆 0 列 → None。`unit` 取三表首頁中第一個符合 `單位[:：](.+?)(?:\(|$)` 的字串（去空白）。`period_*` 取 bs 的；bs 缺則 is、再 cf。`checks` 依 §2.4。`unmapped_labels` 依 §1。

### 2.4 勾稽（`run_cross_checks(rows) -> list[CrossCheck]`，容差 `abs(lhs-rhs) <= 2`，單位仟元）
對 `period in ("current","prior")` 各算一次，固定名稱：

| name | lhs | rhs |
|---|---|---|
| `bs_assets_eq_liab_equity` | `total_assets` | `total_liabilities_and_equity` |
| `bs_assets_sum` | `total_current_assets + total_noncurrent_assets` | `total_assets` |
| `bs_liab_equity_sum` | `total_liabilities + total_equity` | `total_liabilities_and_equity` |
| `is_gross_profit` | `revenue + cogs`（cogs 為負數存） | `gross_profit` |
| `is_operating_income` | `gross_profit + total_opex`（負數存） | `operating_income` |
| `is_pretax` | `operating_income + nonoperating_total` | `pretax_income` |
| `is_net_income` | `pretax_income + income_tax`（負數存） | `net_income` |
| `cf_net_change` | `cfo + cfi + cff + fx_effect` | `net_change_in_cash` |
| `cf_ending` | `cash_beginning + net_change_in_cash` | `cash_ending` |
| `cf_ending_eq_bs_cash` | `cash_ending` | bs `cash` 同期 |
| `cf_pretax_eq_is` | cf `pretax_income_cf` | is `pretax_income` |

任一輸入 None → `passed=None`。金額一律照表內符號存（費用、流出為負），勾稽公式用加法。

---

## 3. 科目對照表（`CANONICAL_KEYS: dict[str, dict[str, str]]`，statement → {正規化 label → key}）
正規化＝NFKC、去空白、`－—–`→`-`、去尾端 `淨額` 不做（保留原文比對，別名逐一列）。**通用台灣 IFRS 科目**（使用者 2026-10-08 傾向通用表），本 run 以下列為最小集合，3653 出現的科目全部覆蓋；每個 key 可列多個別名。

**bs**：`cash`（現金及約當現金）、`fvtpl_current`（透過損益按公允價值衡量之金融資產-流動）、`notes_receivable`（應收票據淨額｜應收票據）、`accounts_receivable`（應收帳款淨額｜應收帳款）、`accounts_receivable_related`（應收帳款-關係人淨額｜應收帳款-關係人）、`other_receivables`（其他應收款）、`inventories`（存貨）、`other_current_assets`（其他流動資產）、`total_current_assets`（流動資產合計）、`fvoci_noncurrent`（透過其他綜合損益按公允價值衡量之金融資產-非流動）、`equity_method_investments`（採用權益法之投資）、`ppe`（不動產、廠房及設備）、`right_of_use_assets`（使用權資產）、`intangible_assets`（無形資產）、`deferred_tax_assets`（遞延所得稅資產）、`prepaid_equipment`（預付設備款）、`refundable_deposits`（存出保證金）、`other_noncurrent_assets`（其他非流動資產-其他｜其他非流動資產）、`total_noncurrent_assets`（非流動資產合計）、`total_assets`（資產總計）、`short_term_borrowings`（短期借款）、`contract_liabilities_current`（合約負債-流動）、`notes_payable`（應付票據）、`accounts_payable`（應付帳款）、`other_payables`（其他應付款）、`current_tax_liabilities`（本期所得稅負債）、`lease_liabilities_current`（租賃負債-流動）、`long_term_borrowings_current`（一年或一營業週期內到期長期負債｜一年內到期長期借款）、`other_current_liabilities`（其他流動負債-其他｜其他流動負債）、`total_current_liabilities`（流動負債合計）、`bonds_payable`（應付公司債）、`long_term_borrowings`（長期借款）、`deferred_tax_liabilities`（遞延所得稅負債）、`lease_liabilities_noncurrent`（租賃負債-非流動）、`net_defined_benefit_liabilities`（淨確定福利負債-非流動）、`guarantee_deposits_received`（存入保證金）、`total_noncurrent_liabilities`（非流動負債合計）、`total_liabilities`（負債總計）、`common_stock`（普通股股本）、`advance_receipts_for_stock`（預收股本）、`capital_surplus`（資本公積）、`legal_reserve`（法定盈餘公積）、`special_reserve`（特別盈餘公積）、`unappropriated_earnings`（未分配盈餘）、`other_equity`（其他權益）、`equity_parent`（歸屬於母公司業主之權益合計）、`noncontrolling_interests`（非控制權益）、`total_equity`（權益總計）、`total_liabilities_and_equity`（負債及權益總計）。

**is**：`revenue`（營業收入）、`cogs`（營業成本）、`gross_profit`（營業毛利）、`selling_expenses`（推銷費用）、`admin_expenses`（管理費用）、`rd_expenses`（研究發展費用）、`total_opex`（營業費用合計）、`operating_income`（營業利益）、`interest_income`（利息收入）、`other_income`（其他收入）、`other_gains_losses`（其他利益及損失）、`finance_costs`（財務成本）、`equity_method_share`（採用權益法認列之關聯企業及合資損益之份額）、`nonoperating_total`（營業外收入及支出合計）、`pretax_income`（稅前淨利）、`income_tax`（所得稅費用）、`net_income`（本期淨利）、`oci`（其他綜合損益(淨額)｜其他綜合損益）、`total_comprehensive_income`（本期綜合損益總額）、`net_income_parent`（母公司業主，section 含 `淨利歸屬於`）、`net_income_nci`（非控制權益，section 含 `淨利歸屬於`）、`eps_basic`（基本每股盈餘）、`eps_diluted`（稀釋每股盈餘）。
`合計` 在 IS 亦依 section 分流：`淨利歸屬於` → `net_income_attrib_total`、`綜合損益總額歸屬於` → `tci_attrib_total`（2026-10-09 補）。`母公司業主`／`非控制權益` 兩個 label 在 IS 出現兩次（淨利歸屬／綜合損益歸屬）：以 `section` 區分——section 含 `淨利歸屬於` → `net_income_parent`／`net_income_nci`；section 含 `綜合損益總額歸屬於` → `tci_parent`／`tci_nci`；bs 的 `非控制權益` → `noncontrolling_interests`（對照表按 statement 分開，不衝突）。

**cf**：`pretax_income_cf`（本期稅前淨利）、`depreciation`（折舊費用）、`amortization`（攤銷費用）、`impairment_loss_receivables`（預期信用減損損失(迴轉利益)）、`finance_costs_adj`（財務成本）、`interest_income_adj`（利息收入）、`dividend_income_adj`（股利收入）、`change_notes_receivable`（應收票據）、`change_receivables`（應收帳款）、`change_receivables_related`（應收帳款-關係人）、`change_other_receivables`（其他應收款）、`change_inventories`（存貨）、`change_other_current_assets`（其他流動資產）、`change_contract_liabilities`（合約負債）、`change_notes_payable`（應付票據）、`change_payables`（應付帳款）、`change_other_payables`（其他應付款）、`change_other_current_liabilities`（其他流動負債）、`cash_from_operations_before_tax`（營運產生之現金流入｜營運產生之現金流入(流出)）、`interest_paid`（支付之利息）、`income_tax_paid`（支付之所得稅）、`cfo`（營業活動之淨現金流入｜營業活動之淨現金流入(流出)｜營業活動之淨現金流出）、`capex`（取得不動產、廠房及設備）、`ppe_disposal_proceeds`（處分不動產、廠房及設備價款）、`intangible_purchase`（購置無形資產）、`prepaid_equipment_increase`（預付設備款增加）、`dividends_received`（收取之股利）、`interest_received`（收取之利息）、`cfi`（投資活動之淨現金流出｜投資活動之淨現金流入｜投資活動之淨現金流入(流出)）、`short_term_borrowings_increase`（短期借款增加）、`short_term_borrowings_decrease`（短期借款減少）、`long_term_borrowings_proceeds`（舉借長期借款）、`long_term_borrowings_repayment`（償還長期借款）、`lease_principal_repayment`（租賃負債本金償還）、`bonds_issued`（發行應付公司債）、`bonds_repaid`（應付公司債償還）、`dividends_paid`（發放現金股利）、`cff`（籌資活動之淨現金流入(流出)｜籌資活動之淨現金流入｜籌資活動之淨現金流出）、`fx_effect`（匯率變動對現金及約當現金影響數）、`net_change_in_cash`（本期現金及約當現金增加(減少)數｜本期現金及約當現金增加數｜本期現金及約當現金減少數）、`cash_beginning`（期初現金及約當現金餘額）、`cash_ending`（期末現金及約當現金餘額）。
cf 的 `應收帳款`／`存貨` 等 label 與 bs 同名，對照表按 statement 分開。

**2026-10-09 真實資料補列（3653 全覆蓋所需，reviewer 🟡1 同步）**：
- is：`remeasurement_defined_benefit`（確定福利計畫之再衡量數）、`fvoci_equity_gain_loss`（透過其他綜合損益按公允價值衡量之權益工具投資未實現評價損益）、`oci_tax_nonreclass`（與不重分類之項目相關之所得稅）、`oci_nonreclass_total`（不重分類至損益之項目總額）、`fx_translation_difference`（國外營運機構財務報表換算之兌換差額）、`oci_reclass_total`（後續可能重分類至損益之項目總額）、`net_income_attrib_total`／`tci_attrib_total`（`合計` 依 section 分流）。
- cf：`fvtpl_gain_adj`（透過損益按公允價值衡量之金融資產利益）、`ppe_disposal_loss_adj`（處分不動產、廠房及設備之損失(利益)）、`lease_modification_loss`（租賃修改損失）、`equity_method_share_adj`（採用權益法認列之關聯企業及合資損益之份額）、`impairment_reversal_nonfinancial`（非金融資產減損迴轉利益）、`unrealized_fx_gain`（未實現外幣兌換淨利益）、`bond_buyback_gain`（買回公司債利益）、`change_net_defined_benefit`（淨確定福利負債-非流動）、`fvtpl_purchase`（取得透過損益按公允價值衡量之金融資產）、`fvtpl_disposal_proceeds`（處分透過損益按公允價值衡量之金融資產）、`fvoci_disposal_proceeds`（處分透過其他綜合損益按公允價值衡量之金融資產）、`change_refundable_deposits`（存出保證金減少(增加)）、`other_noncurrent_assets_increase`（其他非流動資產增加）、`guarantee_deposits_received_increase`（存入保證金增加）、`dividends_paid_to_nci`（子公司發放予非控制權益之現金股利）、`employee_stock_option_exercised`（員工執行認股權）。

---

## 4. 接線

### 4.1 `tables.py`
- `TablesBundle` 加欄 `statements: "StatementLedger | None" = None`（放最後，保留既有位置參數順序）；`to_dict` 加 `"statements": self.statements.to_dict() if self.statements else None`。
- `extract_tables` 末段（T10 之後、`return` 之前）：`statements = extract_statements(fs, fs_anchors)`；三表各自 0 列（或 statements 為 None）→ `missing.append` 對應名稱 `"FS_BS"`／`"FS_IS"`／`"FS_CF"`（新常數 `_MISS_FS_BS`…；`missing_tables` 註解的固定名稱清單同步補）。
- `consolidated_key_lines`、`parent_key_lines`、`parent_cost_coverage` 不動。

### 4.2 `report.py`
- 新增 `## 附錄 D：合併財報三表勾稽`（放在附錄 C 之後）：`_appendix_d(bundle)`——無帳本 → 一句「無合併財報或三表未解析」；有 → ①一行：單位、期間（`114 年度 vs 113 年度`）、三表列數、未對照科目數；②勾稽表（欄：項目、期間、左值、右值、結果 ✅／❌／—）；③未對照科目清單（逗號接，最多 30 個，超過加「…」）。逐列數字不進 md（只在 raw.json 的 `bundle.statements.rows`）。
- `raw.json` 不需改碼（`bundle.to_dict()` 已含）。

### 4.3 `README.md`
tw-equity 段加一句：「合併財報三表逐列解析為標準化帳本（`raw.json` 的 `bundle.statements`），含勾稽結果（附錄 D）。」

---

## 5. 測試與 fixture

- `tests/fixtures/tw_equity/make_fs_fixture.py` 的 `_SELECTED_PAGES` 加 `13`、`15` → 重產 `fs_3653_pages.json`（既有頁內容不變，既有測試不受影響）。
- `tests/tw_equity/test_statements.py`（合成列）：note 剝除（`六(五)(二十一)`＋續行 `及七 ( 11,841,587 ) …` → label `營業成本`、note `六(五)(二十一)及七`、current −11841587、current_pct −58）；續行合併（`透過損益按公允價值衡量之金融資產-流 六(二)` ＋ `動 157,576 1 - -` → label `透過損益按公允價值衡量之金融資產-流動`、prior None）；群組標題設 section 不產 row；尾列丟棄；期間列解析（三種寫法）；bs／is 2 token 與 4 token；cf 1／2 token；對不到的 label → key None 且進 `unmapped_labels`；IS `母公司業主` 依 section 分 key；`get()`；`to_dict` 可 `json.dumps`。
- `tests/tw_equity/test_statements_checks.py`：11 個勾稽各一組通過案例、一組失敗案例、一組 None 案例。
- `tests/tw_equity/test_statements_real.py`（真實 fixture p10–15）：`statement_pages` → bs=[10,11]、is=[12]、cf=[14,15]；`get("total_assets")==(27968731, 18461872)`、`get("net_income")==(5310342, 3415162)`、`get("cfo")==(4773519, 2890676)`、`get("capex")==(-829582, -217200)`、`get("cash_ending")==(9134067, 2267253)`、`get("cogs")==(-11841587, -8912721)`、`get("fvtpl_current")==(157576, None)`；11 個勾稽 × 2 期 **全部 passed=True**；`unmapped_labels` 為空（3653 全覆蓋）。
- `tests/tw_equity/test_tables_statements.py`：`extract_tables` 有 fs → `bundle.statements` 非 None、`to_dict()["statements"]["row_counts"]`；fs=None → `statements is None` 且 `missing_tables` 含 `FS_BS`、`FS_IS`、`FS_CF`；既有 `test_tables_integration` 的 `missing_tables` 斷言若為「等於固定清單」須同步加三個名稱（writer 於 task 檔記退場／修改）。
- `tests/tw_equity/test_report_statements.py`：有帳本 → md 含 `## 附錄 D` 與 11 列勾稽；無帳本 → 含「未解析」一句；raw.json 的 `bundle.statements.rows` 長度 = row_counts 合計。
- 既有 `tests/tw_equity/test_e2e*.py`：dry-run 全綠（帳本只是新增鍵）。

---

## 6. 驗收（本 run DoD）
1. `./.venv/bin/python -m pytest -q tests/tw_equity` 全綠；全套 `./.venv/bin/python -m pytest -q` 無新增失敗。
2. 真實 3653 合併財報：bs ≥ 45 列、is ≥ 25 列、cf ≥ 45 列；11 勾稽 × 2 期全過；`unmapped_labels == []`（以 `test_statements_real.py` 為憑據）。
3. `python main.py 3653 --market tw-equity --dry-run` 產出的 `raw.json` 含 `bundle.statements`，md 含附錄 D（step 5 實跑，不打 API）。

## 7. 開放問題（HITL 裁示點）
- Q1 對照表範圍：本 Spec 列通用最小集合（約 110 個 key，3653 全覆蓋）。其他公司出現的新科目會進 `unmapped_labels`，由後續 run 增補別名。**建議：接受。**
- Q2 報告呈現：附錄 D 只放勾稽與統計，不放逐列數字（約 140 列會讓 md 過長；逐列在 raw.json）。**建議：接受。**
- Q3 勾稽容差 2 仟元。**建議：接受。**

## 8. Out of Scope
指標公式與 FCF／bridge 歸因（階段 2）；問答 skill 與 `--ask`（階段 3）；年報現金流量／特別記載／重要契約接入（階段 4）；個體財報三表；附註明細表；權益變動表；前一年度合併財報（輸入檔無）。
