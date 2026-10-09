# Spec：台股財報 Phase 2-2 指標公式登錄表＋變動歸因（bridge）引擎（`tw-equity`）

> run_id：`2026-10-09-tw-equity-metrics`。前序：`spec/2026-10-09-tw-equity-statements.md`（階段 1 事實帳本，commit a89f7ce）。
> 本 Spec 自足。上位目標（使用者 2026-10-08 裁示）：會計問答——「FCF 多少」「影響 FCF 最多的是什麼」要能以可追溯數字回答。**本 run＝階段 2**：所有數字由程式算，LLM 不算術；階段 3（問答 skill＋`--ask`）不在本 run。

---

## 0. 定位與前提

### 0.1 範圍
新檔 `runtime/tw_equity/metrics.py`：①**指標登錄表**（每個指標＝key、中文名、公式字串、輸入 key、計算函式），對 `StatementLedger` 的本期／上期各算一次，輸出含輸入值與公式（可追溯）；②**bridge 歸因**（目標項的本期−上期變動，分解到各組成項的變動，依絕對值排序，含殘差）；③勾稽：bridge 組成項變動加總＋殘差＝目標變動（恆等）。結果併入 `TablesBundle.metrics`（隨 `tables_json` 送 skill、隨 `raw.json` 落地），報告加附錄 E。`tw_financial_analysis` skill 的 Input 說明補一句可讀 `metrics` 區（skill 不改邏輯）。

### 0.2 實測事實（2026-10-09，3653 之 114 年度帳本，`data/output/3653/3653_20261009_0053_raw.json` → `bundle.statements`）
| 項目 | 事實 | 處置 |
|---|---|---|
| 帳本 key 覆蓋 | bs 49 key、is 27 key、cf 58 key（全文見 `statements.CANONICAL_KEYS`）；3653 全對照 | 指標只用這些 key；缺 key 的指標回 None、不 raise |
| 符號慣例 | 費用／流出在帳本為**負數**（`cogs=-11,841,587`、`capex=-829,582`、`income_tax=-1,296,613`、`dividends_paid=-2,072,369`） | 公式用加法：`fcf = cfo + capex`；比率分母取絕對值時在公式字串明示 `abs()` |
| 單位 | 仟元；EPS 為元 | `MetricResult.unit`：金額型 `"仟元"`、比率型 `"%"`、天數型 `"天"`、倍數型 `"x"` |
| 兩期 | 單一帳本含本期（114）與上期（113）；上一年度合併財報輸入檔無 | 指標與 bridge 皆以同一帳本的兩欄算；平均值型（如平均存貨）本 run **不做**，一律期末值（§1.2 公式字串明示） |
| 既有 `TwoYearTable.derived`（T7b 的毛利率等） | 由年報財務績效表算，供舊 skill 用 | 不動；帳本指標為新增並行資料，Spec 註明兩者來源不同（年報 vs 合併財報），數值可能差小數 |
| 既有 `cross_year.py` | 比對兩年度 `TablesBundle` 的年報表格 | 不動；指標跨年序列留待有多年度帳本時再做 |

### 0.3 不碰的既有檔案
`runtime/tw_equity/statements.py`、`pdf_doc.py`、`doc_anchor.py`、`sections.py`、`cross_year.py`、`tw_pipeline.py`、`main.py`、`runtime/agent_runner.py`、`runtime/eval_runner.py`、`runtime/mock_outputs.json`、`agents/**`、`skills/**`（**例外**：`skills/tw/tw_financial_analysis.md` 只改 Input 節一句與 `last_modified`）。
允許改：新檔 `runtime/tw_equity/metrics.py`；`runtime/tw_equity/tables.py`（只加 `TablesBundle.metrics` 欄、`to_dict` 一鍵、`extract_tables` 末段一行接線）；`runtime/tw_equity/report.py`（只加附錄 E 與 render 函式）；`README.md`（一句）；`tests/tw_equity/**`。

---

## 1. 資料模型與登錄表（`runtime/tw_equity/metrics.py`）

### 1.1 dataclass
```python
@dataclass(frozen=True)
class MetricSpec:
    key: str; name: str; formula: str; inputs: tuple[str, ...]; unit: str  # unit ∈ {"仟元","%","天","x","元"}
    fn: Callable[[dict[str, float]], float | None]   # 輸入全非 None 才呼叫；分母 0 → None

@dataclass
class MetricResult:
    key: str; name: str; formula: str; unit: str; period: str   # "current"|"prior"
    value: float | None; inputs: dict[str, float | None]        # 實際代入值（可追溯）
    def to_dict(self) -> dict

@dataclass
class BridgeComponent:
    key: str; name: str; current: float | None; prior: float | None; delta: float | None
    share: float | None    # delta / target_delta；target_delta 為 0 或 None → None

@dataclass
class BridgeResult:
    target: str; name: str; target_current: float | None; target_prior: float | None; target_delta: float | None
    components: list[BridgeComponent]   # 依 |delta| 由大到小排序（delta None 排最後）
    residual: float | None              # target_delta − Σ(component.delta)；任一 None → None
    top_drivers: list[str]              # 前 3 個 |delta| 最大的 component.key（delta 非 None）
    def to_dict(self) -> dict

@dataclass
class MetricsPack:
    period_current: str; period_prior: str
    metrics: list[MetricResult]         # 登錄表順序 × (current, prior)
    bridges: list[BridgeResult]         # 登錄表順序
    def get(self, key: str, period: str = "current") -> float | None
    def to_dict(self) -> dict           # 鍵：period_current、period_prior、metrics、bridges、index{metric_key: {"current": v, "prior": v}}
```

### 1.2 指標登錄表 `METRIC_SPECS: list[MetricSpec]`（順序固定；`formula` 為人讀字串，單位仟元，比率 ×100）
| key | name | formula（inputs） | unit |
|---|---|---|---|
| `fcf` | 自由現金流 | `cfo + capex` | 仟元 |
| `fcf_margin` | 自由現金流率 | `fcf / revenue * 100` | % |
| `gross_margin` | 毛利率 | `gross_profit / revenue * 100` | % |
| `operating_margin` | 營業利益率 | `operating_income / revenue * 100` | % |
| `net_margin` | 淨利率 | `net_income / revenue * 100` | % |
| `ebitda` | EBITDA | `operating_income + depreciation + amortization` | 仟元 |
| `ebitda_margin` | EBITDA 率 | `ebitda / revenue * 100` | % |
| `cfo_to_net_income` | 營業現金流／淨利 | `cfo / net_income` | x |
| `capex_to_depreciation` | 資本支出／折舊 | `abs(capex) / depreciation` | x |
| `capex_to_revenue` | 資本支出率 | `abs(capex) / revenue * 100` | % |
| `dso` | 應收帳款天數（期末） | `(accounts_receivable + accounts_receivable_related) / revenue * 365` | 天 |
| `dio` | 存貨天數（期末） | `inventories / abs(cogs) * 365` | 天 |
| `dpo` | 應付帳款天數（期末） | `accounts_payable / abs(cogs) * 365` | 天 |
| `ccc` | 現金轉換循環 | `dso + dio - dpo` | 天 |
| `current_ratio` | 流動比率 | `total_current_assets / total_current_liabilities * 100` | % |
| `quick_ratio` | 速動比率 | `(total_current_assets - inventories) / total_current_liabilities * 100` | % |
| `interest_bearing_debt` | 有息負債 | `short_term_borrowings + long_term_borrowings_current + long_term_borrowings + bonds_payable + lease_liabilities_current + lease_liabilities_noncurrent`（缺 key 視為 0，**例外規則**：本指標的輸入允許缺，見 §2.1） | 仟元 |
| `net_debt` | 淨負債 | `interest_bearing_debt - cash` | 仟元 |
| `debt_to_equity` | 有息負債／權益 | `interest_bearing_debt / total_equity * 100` | % |
| `liabilities_to_assets` | 負債比率 | `total_liabilities / total_assets * 100` | % |
| `interest_coverage` | 利息保障倍數 | `operating_income / abs(finance_costs)` | x |
| `roe` | 股東權益報酬率（期末） | `net_income_parent / equity_parent * 100` | % |
| `roa` | 資產報酬率（期末） | `net_income / total_assets * 100` | % |
| `asset_turnover` | 總資產週轉率（期末） | `revenue / total_assets` | x |
| `rd_intensity` | 研發費用率 | `abs(rd_expenses) / revenue * 100` | % |
| `opex_ratio` | 營業費用率 | `abs(total_opex) / revenue * 100` | % |
| `effective_tax_rate` | 有效稅率 | `abs(income_tax) / pretax_income * 100` | % |
| `dividend_payout` | 現金股利支付率 | `abs(dividends_paid) / net_income_parent * 100` | % |
| `cash_to_assets` | 現金占總資產 | `cash / total_assets * 100` | % |
| `working_capital` | 營運資金 | `total_current_assets - total_current_liabilities` | 仟元 |

衍生指標（`fcf_margin`、`ebitda_margin`、`ccc`、`net_debt`、`debt_to_equity`）的輸入可引用先前指標 key（求值順序＝登錄表順序；`inputs` 內寫指標 key）。`net_income_parent`／`equity_parent` 缺時 `roe` 回 None（不以合併淨利代用）。

### 1.3 Bridge 登錄表 `BRIDGE_SPECS: list[BridgeSpec]`（`BridgeSpec(target, name, components: tuple[str, ...])`；target 可為帳本 key 或指標 key）
| target | name | components（帳本／指標 key，順序即預設順序） |
|---|---|---|
| `fcf` | 自由現金流變動 | `cfo`, `capex` |
| `cfo` | 營業現金流變動（間接法） | `pretax_income_cf`, `depreciation`, `amortization`, `change_receivables`, `change_receivables_related`, `change_inventories`, `change_payables`, `change_other_payables`, `change_contract_liabilities`, `change_other_receivables`, `change_other_current_assets`, `change_other_current_liabilities`, `change_notes_receivable`, `change_notes_payable`, `interest_paid`, `income_tax_paid`, `finance_costs_adj`, `interest_income_adj`, `dividend_income_adj`, `fvtpl_gain_adj`, `unrealized_fx_gain`, `impairment_loss_receivables`, `ppe_disposal_loss_adj`, `equity_method_share_adj`, `impairment_reversal_nonfinancial`, `lease_modification_loss`, `bond_buyback_gain`, `change_net_defined_benefit` |
| `net_income` | 淨利變動 | `revenue`, `cogs`, `selling_expenses`, `admin_expenses`, `rd_expenses`, `interest_income`, `other_income`, `other_gains_losses`, `finance_costs`, `equity_method_share`, `income_tax` |
| `operating_income` | 營業利益變動 | `revenue`, `cogs`, `total_opex` |
| `net_change_in_cash` | 現金變動 | `cfo`, `cfi`, `cff`, `fx_effect` |
| `cfi` | 投資現金流變動 | `capex`, `ppe_disposal_proceeds`, `intangible_purchase`, `prepaid_equipment_increase`, `fvtpl_purchase`, `fvtpl_disposal_proceeds`, `fvoci_disposal_proceeds`, `other_noncurrent_assets_increase`, `change_refundable_deposits`, `dividends_received`, `interest_received` |
| `cff` | 籌資現金流變動 | `short_term_borrowings_increase`, `short_term_borrowings_decrease`, `long_term_borrowings_proceeds`, `long_term_borrowings_repayment`, `bonds_issued`, `bonds_repaid`, `lease_principal_repayment`, `dividends_paid`, `dividends_paid_to_nci`, `employee_stock_option_exercised`, `guarantee_deposits_received_increase` |
| `total_assets` | 總資產變動 | `cash`, `accounts_receivable`, `inventories`, `ppe`, `prepaid_equipment`, `other_noncurrent_assets`, `fvtpl_current`, `fvoci_noncurrent`, `right_of_use_assets`, `deferred_tax_assets`, `other_current_assets`, `other_receivables`, `accounts_receivable_related`, `notes_receivable`, `equity_method_investments`, `intangible_assets`, `refundable_deposits` |

component 缺 key（帳本**無該列**；列存在而值為「-」者視為 0、不算缺）→ 該 component 的 current／prior／delta 皆 None、**不計入 Σ**、不入 top_drivers；殘差＝target_delta − Σ(非 None delta)。bridge 的 component 名稱（`name`）取自帳本該列 `label`（第一個相符列），指標 key 則取 `MetricSpec.name`；缺列時用 key 本身。

---

## 2. 計算契約

### 2.1 `compute_metrics(ledger: StatementLedger | None) -> MetricsPack | None`
- ledger None → None。
- 對每個 `MetricSpec`、每期：以帳本第一個相符列取值——**列存在但該期為 `-`（None）→ 視為 0**（財報的「-」即 0；2026-10-09 實測 `bonds_issued` 上期「-」致 cff 殘差 5.97M 後補列）、**無該列 → None**（指標 key 則取已算出的指標值）；**任一輸入 None → value None**（例外：`interest_bearing_debt` 缺的 key 視為 0，但全部缺 → None）；分母 0 → None。`inputs` 記實際代入值（含 None）。
- 回傳 `MetricsPack`，`metrics` 順序＝登錄表 × (current, prior)。

### 2.2 `compute_bridges(ledger, pack) -> list[BridgeResult]`
- 對每個 `BridgeSpec`：target 值取帳本或指標（current／prior）；component 同；取值規則同 §2.1（列存在而「-」→ 0；無列 → None）。`delta = current − prior`（任一 None → None）。`share = delta / target_delta`（target_delta None 或 0 → None）。`components` 依 `|delta|` 降序（None 殿後，原順序）；`top_drivers` 取前 3 個非 None。`residual` 依 §1.3。
- **恆等檢查**：`residual` 非 None 時 `target_delta == Σ delta + residual`（浮點容差 1e-6）——測試斷言。

### 2.3 3653 預期值（真實 fixture，容差 ±1 仟元／比率 ±0.01）
- `fcf`：current `4,773,519 + (−829,582) = 3,943,937`；prior `2,890,676 + (−217,200) = 2,673,476`
- `gross_margin` current `8,433,990/20,275,577*100 = 41.60`；`net_margin` current `26.19`
- `cfo_to_net_income` current `4,773,519/5,310,342 = 0.90`
- `dso` current `(5,290,997+122,166)/20,275,577*365 = 97.45`
- `current_ratio` current `18,566,576/4,453,346*100 = 416.91`（與年報財務分析表「流動比率 416.91」一致——作為對帳點）
- `interest_bearing_debt` current：`short_term_borrowings`／`long_term_borrowings`／`long_term_borrowings_current`／`bonds_payable` 3653 帳本皆無 → 視為 0；`lease_liabilities_current 40,274 + lease_liabilities_noncurrent 46,693 = 86,967`（注意：3653 於 114 年發行可轉換公司債 5,197,445 仟元但年底已全數轉換，BS 無應付公司債列——帳本如實反映）
- bridge `fcf`：target_delta `1,270,461`；components delta：cfo `1,882,843`、capex `−612,382`；residual 0；top_drivers `["cfo","capex"]`
- bridge `net_change_in_cash`：target_delta `8,755,184`；cff delta `5,291,724`、cfo `1,882,843`、cfi `1,549,501`、fx `31,116`；residual 0；top_drivers `["cff","cfo","cfi"]`

---

## 3. 接線
- `tables.py`：`TablesBundle.metrics: "MetricsPack | None" = None`（最後）；`to_dict` 加 `"metrics"`；`extract_tables` 末段 `metrics = compute_metrics(statements)` 並傳入（在函式內 import `metrics` 以免循環）。
- `report.py`：`## 附錄 E：關鍵指標與變動歸因`（附錄 D 之後）：①指標表（欄：指標、公式、本期、上期、單位；value None 顯示 `—`）；②每個 bridge 一小表（標題含 target 名與 Δ；欄：組成項、本期、上期、Δ、占比%；最後一列殘差）；無 metrics → 一句「無帳本，未計算指標」。
- `skills/tw/tw_financial_analysis.md`：Input 的 `tables_json` 句尾加「；`metrics` 區（階段 2 指標與 bridge，含公式與輸入值）可直接引用，不重算」，`last_modified` 改 2026-10-09。
- `README.md`：tw-equity 段加一句：「帳本衍生 30 項指標與 8 組變動歸因（附錄 E、`raw.json` 的 `bundle.metrics`）。」

## 4. 測試
- `tests/tw_equity/test_metrics.py`（合成帳本 builder）：每個指標至少一組已知值；缺輸入 → None；分母 0 → None；`interest_bearing_debt` 缺 key 視 0／全缺 None；衍生指標引用先前指標；`MetricsPack.get`／`to_dict` 可 `json.dumps`。
- `tests/tw_equity/test_metrics_bridges.py`：排序、share、殘差恆等、缺 component 不計入、top_drivers ≤3、名稱取自帳本 label。
- `tests/tw_equity/test_metrics_real.py`：真實 fixture（`fs_3653_pages.json` p10–15）→ `extract_statements` → `compute_metrics`，斷言 §2.3 全部值。
- `tests/tw_equity/test_tables_metrics.py`／`test_report_metrics.py`／`test_e2e_metrics.py`：接線、附錄 E 內容（30 指標列、8 bridge 表、None 顯示 `—`）、dry-run raw.json 含 `bundle.metrics`；既有「標題數 12／附錄數 4」斷言改 13／5（只改斷言資料）。

## 5. 驗收
1. `pytest -q tests/tw_equity` 全綠；全套無新增失敗。
2. 真實 3653：§2.3 全部值；8 個 bridge 殘差（有值者）絕對值 ≤ 1 仟元——`cfo` bridge 的殘差允許非 0（間接法調整項未全列者計入殘差），但 §2.3 兩個 bridge 殘差須為 0。
3. `python main.py 3653 --market tw-equity --dry-run` 的 raw.json 含 `bundle.metrics`、md 含附錄 E（step 5 實跑）。

## 6. 開放問題（HITL）
- Q1 指標一律期末值（不做平均）。**建議：接受**（階段 4 有五年表後再做平均）。
- Q2 `cfo` bridge 列 28 個調整項，殘差吸收未列者。**建議：接受**。
- Q3 附錄 E 放全部 30 指標＋8 bridge 表（約 150 列 md）。**建議：接受**（LLM 問答靠 raw.json，md 給人看）。

## 7. Out of Scope
問答 skill 與 `--ask`（階段 3）；跨年度指標序列；平均值型指標；個體財報；年報五年財務分析表對帳（階段 4）。
