# Spec：台股財報分析 pipeline Phase 1B-1（`tw-equity`）真實財報校正＋T9／T10＋四個敘述 skill

> run_id：`2026-10-08-tw-equity-phase-1b1`。上位計畫：`specs/tw_equity_plan.md`（§6 Phase 1B）。前一 run 的 Spec：`specs/tw-equity-phase-1a.md`（以下簡稱「1A Spec」，節次以 `1A §x` 表示）。兩檔在工作目錄、`specs/` 為 gitignored。
> 本 Spec 自足：不依賴對話；凡與上位計畫或 1A Spec 不同處，以本 Spec 為準（§0.2 列出差異與原因）。

---

## 0. 定位與前提

### 0.1 定位與 Phase 1B 的切分

使用者 2026-10-08 裁示：Phase 1B 拆成兩個 run。

| run | 範圍 |
|---|---|
| **1B-1（本 run）** | ①合併財報真實版面校正（1A §6 Q1 的欠帳）②T9 背書保證／資金貸與 ③T10 股權質押＋前十大股東 ④四個敘述 skill：`tw_kam_analysis`、`tw_business_analysis`、`tw_customer_supplier`、`tw_governance_flags` ⑤報告加四個主節。驗收以**單一年度**（3653，114 年度）進行 |
| 1B-2（下一 run，本 Spec 不實作） | 跨年比較：輸入檔加前一年、前一年跑 skill、`cross_year_compare`、報告跨年節；2024 年報（`tw_report/3653_2024年報.pdf`）有 17 頁字型無 ToUnicode 對照（`(cid:NNNN)` 亂碼），以 Azure DI OCR 備援（重用 `runtime/tw_credit/adapters.py` 的 `AzureDIAdapter`，`config.json` 已有 `azure.di_endpoint`／`di_key`） |

### 0.2 實測事實（2026-10-08，`tw_report/3653_2025Q4合併財報.pdf`，74 頁，114／113 年度合併財報＋查核報告；`tw_report/2025_3653_健策年報.pdf`）

| 1A 假設 | 實測事實 | 本 Spec 處置 |
|---|---|---|
| 財報章節名在頁首 300 字內（1A §2.3 演算法） | 附註標題在頁面中間（例：「(五)存貨」在 p31 第 245 字、「七、關係人交易」在 p51 第 884 字）。1A `find_sections` 在本檔的結果全錯（`fs_bs`／`fs_is`／`fs_cf` 皆錨到 p5 查核報告） | 財報改用**標題行錨定**（§2.2）。年報既有 key 的錨定不變 |
| 財報表格可由 pdfplumber `extract_tables` 取得 | 本檔**每一頁** `extract_tables` 皆回空（無框線表）；`extract_text` 數字含字距（`$ 2 ,094,512`）；p31 存貨表為旋轉文字，`extract_text` 輸出逐字直排亂序 | `pdf_doc` 加「列文字」通道 `Page.lines`（§2.1），由字詞座標重組成列。實測 PyMuPDF `get_text("words")` 依 y 分群、x 排序後，p12 損益表、p31 存貨、p46–47 費用性質、p67 附表一皆得到乾淨的列 |
| 損益表「營業成本」在同一行有兩個金額 | p12：「營業成本 六(五)(二十一)」與「及七 ( 11,841,587 ) ( 58 ) ( 8,912,721 ) ( 62 )」分兩行（附註欄換行） | 關鍵列解析加「續行合併」（§2.3.1） |
| T9 是表格 | 附註十三(一) p64 有文字「1.資金貸與他人：無。」「2.為他人背書保證：請詳附表一。」；附表一 p67 為無框線表，名稱跨兩行（「健策精密工業股份」＋「有限公司」） | T9＝文字狀態＋附表列（§2.3.3） |
| — | 年報 p8（貳章首頁）為旋轉文字，pdfplumber `extract_text` 輸出反序字（「告報理治司公、貳」）；PyMuPDF 正常讀出「貳、公司治理報告」 | 治理相關年報 key 用 `Page.lines` 的標題行錨定（§2.2.3） |
| — | 年報 p57「(三)股權質押資訊」與 p58「八、持股比例占前十名之股東…」的表格，pdfplumber `extract_tables` 可正常取得 | T10 用既有 `tables` 通道解析（§2.3.4） |

### 0.3 不碰的既有檔案
`runtime/tw_credit/**`、`runtime/orchestrator.py`、`runtime/jp_*.py`、`runtime/report_writer.py`（只 import，不改）、`runtime/section_splitter.py`、`agents/analyst_agent.md`、`main.py`、1A 的三個 skill（`skills/tw/tw_cost_structure.md`、`tw_financial_analysis.md`、`tw_footnotes_quality.md`）。
允許改：`runtime/tw_equity/**`、`runtime/eval_runner.py`（只在 `REQUIRED_KEYS` 加 4 個 tw_ 條目）、`runtime/mock_outputs.json`（加 4 個 tw_ 條目）、`requirements.txt`（加 PyMuPDF，見 §6 Q1）、`tw_equity_inputs/3653.json`、`skills/tw/` 新增 4 檔、`tests/tw_equity/**`、`tests/fixtures/tw_equity/**`。

---

## 1. 輸入

`tw_equity_inputs/3653.json` 的 `consolidated_fs_path` 改為 `"tw_report/3653_2025Q4合併財報.pdf"`；`parent_fs_path` 維持 `null`（個體財報仍未取得，T1–T3 仍為 `missing_tables`）。輸入檔格式（1A §1.1）不變。

---

## 2. 模組契約（`runtime/tw_equity/`）

### 2.1 `pdf_doc.py`：加列文字通道

```python
@dataclass
class Page:
    number: int
    text: str
    tables: list[list[list[str | None]]]
    lines: list[str] = field(default_factory=list)   # 新增

class PdfDoc:
    def lines_of(self, start: int, end: int) -> list[str]   # 新增；含兩端，依頁序串接

def load_pdf(path, *, cache_dir=None, _opener=None, _line_opener=None) -> PdfDoc
```

- `lines` 產生法：PyMuPDF `page.get_text("words")` → 依字詞底緣 y（`y1`）分群，相鄰字詞 y 差 ≤3pt 為同一列 → 列內依 `x0` 排序、以單一空白接合 → 去頭尾空白、丟棄空列。列序依 y 由上而下
- `_line_opener`：測試注入點，回傳物件有 `__getitem__(i)`／`__len__`，每頁有 `get_text("words")`（回傳 tuple 序列 `(x0, y0, x1, y1, word, ...)`）。預設 `fitz.open`
- `_CACHE_VERSION` 加 1；`to_json`／`from_json` 加 `lines` 欄（`from_json` 遇缺 `lines` 的舊格式 → `lines=[]`，供 1A 既有 fixture 相容）
- 頁數以 `_opener` 結果為準；兩個 opener 頁數不同 → `ValueError`

### 2.2 `doc_anchor.py`：標題行錨定

#### 2.2.1 新 API

```python
@dataclass(frozen=True)
class HeadingAnchor:
    keywords: list[str]          # 依優先序
    enum: bool                   # True＝須有編號前綴；False＝整列（去空白後）等於關鍵字
    after: str | None = None     # 起頁須 ≥ 指定 key 的起頁（解決「會計政策」節同名標題）

def find_heading_sections(doc: PdfDoc, anchors: dict[str, HeadingAnchor], *,
                          required: set[str]) -> dict[str, PageRange | None]
```

演算法（只讀 `Page.lines`）：
1. 列正規化：NFKC，刪除所有空白（處理「合 併 資 產 負 債 表」字距）
2. 編號前綴 regex：`^(?:[壹貳參肆伍陸柒捌玖拾]+、|[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[)）]|\d+\.)`（章級大寫數字為主 flow 2026-10-08 裁決補入：年報 p8 列為「貳、公司治理報告 現在持有股數 股數」，標題與表格欄名併列，整列比對無法命中）
3. 標題列判定：
   - `enum=True`：列以「編號前綴＋關鍵字」開頭，且列尾**不是**頁碼（`\d+(?:[~～\-]\d+)?$` 不成立）
   - `enum=False`：列等於關鍵字，或列等於「編號前綴＋關鍵字」
4. 目錄頁：同一頁命中 ≥3 個不同 key 的頁；所有頁碼 ≤ 最後一個目錄頁的頁不參與起頁判定
5. 起頁：第一個符合的頁（且滿足 `after`）。終頁：所有已找到 key 依起頁排序，下一個起頁較大的 key 的起頁 − 1；最後一個到文件末頁
6. `required` 缺 → `AnchorError`（訊息格式比照 1A）

#### 2.2.2 合併財報 key（取代 1A 的 `FS_ANCHORS` 用於合併財報；`FS_ANCHORS` 常數保留不刪）

`FS_HEADING_ANCHORS`，3653 實測期望起頁：

| key | keywords | enum | after | 3653 起頁 |
|---|---|---|---|---|
| `fs_audit_kam` | 關鍵查核事項 | False | — | 5 |
| `fs_bs` | 合併資產負債表 | False | — | 10 |
| `fs_is` | 合併綜合損益表 | False | — | 12 |
| `fs_cf` | 合併現金流量表 | False | — | 14 |
| `fs_note_items` | 重要會計項目之說明 | True | — | 29 |
| `fs_note_inventory` | 存貨 | True | `fs_note_items` | 31 |
| `fs_note_expense_nature` | 費用性質之額外資訊 | True | `fs_note_items` | 46 |
| `fs_note_related` | 關係人交易 | True | — | 51 |
| `fs_note_contingent` | 重大或有負債及未認列之合約承諾 | True | — | 55 |
| `fs_note_disclosure` | 附註揭露事項 | True | — | 64 |

required＝`{fs_bs, fs_is}`。個體財報（`PARENT_FS_ANCHORS`＋1A `find_sections`）**不改**：無真實檔可校正。

#### 2.2.3 年報治理 key（新增；年報既有 key 與 1A `find_sections` 呼叫不變）

`GOVERNANCE_HEADING_ANCHORS`（對年報另做一次 `find_heading_sections`，required＝空集合），2025 年報實測期望起頁：

| key | keywords | enum | 2025 起頁 |
|---|---|---|---|
| `ar_governance` | 公司治理報告 | True | 8 |
| `ar_pledge` | 股權質押資訊 | True | 57 |
| `ar_top10` | 持股比例占前十名之股東 | True | 58 |
| `ar_capital` | 參、募資情形 | False | 59 |
| `ar_operations` | 肆、營運概況 | False | 65 |

`ar_operations` 只作 `ar_capital` 的終點，不進 sections。若某關鍵字以上述 enum 設定無法命中期望頁（例：列尾有其他字），writer 以 3653 真實 fixture 為準調整關鍵字，並在交付報告記錄調整內容；期望起頁不可改。

### 2.3 `tables.py`

#### 2.3.1 列文字共用工具與財報解析改用列通道

```python
def line_amounts(line: str) -> list[float | None]
```
- 先正規化：NFKC；`( 11,841,587 )`／`($ 2,277)` 收成 `(11,841,587)`／`(2,277)`；去 `$`
- 由左至右取金額 token：`\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?`、`\(?\d+(?:\.\d+)?%?\)?`、單獨的 `-`／`－`（→ `None`）。括號 → 負值；`%` 值回傳數字本身（`0.13%`→`0.13`）
- 純百分比欄（如損益表的 `( 58 )`）由呼叫端依欄位位置捨棄

```python
def parse_key_lines_from_lines(lines: list[str], labels: list[str]) -> dict[str, tuple[float | None, float | None]]
```
- 對每個 label：找第一個「去空白後以 label 開頭」且含金額 token 的列；若該列金額 token 數 <2，與下一列合併後再取（續行合併，最多合併 1 列）
- 損益表列格式為「金額 % 金額 %」：token 數 ≥4 取第 1 與第 3 個為 (current, prior)；token 數 2–3 取第 1、2 個
- `營業費用` label：該列無金額時改用以「營業費用合計」開頭的列
- `營業成本`、`營業費用` 回傳絕對值（與 1A 合成 fixture 正值語義一致）；其他 label 保留正負號
- 3653 p12 期望：營業收入 (20275577, 14278187)、營業成本 (11841587, 8912721)、營業毛利 (8433990, 5365466)、營業費用 (1935857, 1566907)、營業利益 (6498133, 3798559)、本期淨利 (5310342, 3415162)

```python
def parse_expense_nature_lines(lines: list[str]) -> ExpenseNature | None
```
- 期別列：去空白後整列為 `\d{2,3}年度`；欄頭列含「營業成本」「營業費用」「合計」
- 資料列：label＋3 個金額 token → (cost_of_sales, opex, total)；無 label、以金額開頭的列為小計，label 記為 `"員工福利費用合計"`
- 同一 label 跨期聚合為 1A `ExpenseNatureRow`（各欄為 list，依 periods 順序）
- 3653 p46–47 期望：periods＝["114年度","113年度"]；薪資費用 cost_of_sales [2094512, 1920837]、opex [939419, 788584]、total [3033931, 2709421]；折舊費用 total [629171, 576411]；攤銷費用 cost_of_sales [None, None]、total [18877, 20513]

```python
def parse_inventory_note_lines(lines: list[str]) -> InventoryNote | None
```
- 欄頭列：去空白後含兩個 `\d{2,3}年\d{1,2}月\d{1,2}日`
- 資料列：label（去空白）＋2 金額 → `net`；`cost`／`allowance` 為 `[None, None]`（3653 只揭露淨額；有「成本」「備抵」分欄的版面未見實例，不實作）；無 label 的列為合計，label `"合計"`；合計列之後即結束
- `writedown`：在同節列文字中找 `淨變現價值而認列之銷貨成本\$?([\d,]+)及\$?([\d,]+)`（先去空白），有則 `[current, prior]`
- 3653 p31 期望：商品 [49180, 21891]、製成品 [1438027, 1072266]、在製品 [1482200, 1286372]、原物料 [682934, 681107]、合計 [3652341, 3061636]；writedown [19263, 12851]

`extract_tables` 財報部分：T4／T5／合併關鍵列**先用列通道解析，回 None 才退回 1A 的 table 通道解析**（保持 1A 合成 fixture 測試有效）。

#### 2.3.2 T8 衍生集中度（供 `tw_customer_supplier`；skill 不做算術）

`TablesBundle.to_dict()` 加 `"concentration"`：
```json
{"T8_sales": [{"label": "114年度", "top1_pct": 22.82, "top3_pct": 0.0, "named_total_pct": 0.0}],
 "T8_purchase": []}
```
- 每個年度一筆：`top1_pct`＝rank 1 的 pct；`top3_pct`＝rank 1–3 pct 加總（不足 3 名 → 已列名加總）；`named_total_pct`＝所有已列名 pct 加總；pct 為 None 的項不計入加總，全部為 None → None；表缺 → 空 list。數值四捨五入到小數 2 位

#### 2.3.3 T9 背書保證／資金貸與

```python
@dataclass
class GuaranteeRow:
    no: int | None; guarantor: str; guaranteed: str; relation_code: str | None
    single_limit: float | None; max_balance: float | None; ending_balance: float | None
    drawn: float | None; collateral: float | None; pct_of_net_worth: float | None
    max_limit: float | None; parent_to_sub: str | None; sub_to_parent: str | None; to_china: str | None

@dataclass
class GuaranteesLoans:
    loans_status: str            # "none" | "table" | "unknown"
    guarantees_status: str       # "none" | "table" | "unknown"
    guarantees: list[GuaranteeRow]
    loans_raw: list[str]         # 資金貸與附表的資料列原文（3653 無；只以合成 fixture 測）
    max_pct_of_net_worth: float | None
    def to_dict(self) -> dict

def parse_guarantees_loans(lines: list[str]) -> GuaranteesLoans | None
```
- 輸入：`fs_note_disclosure` 範圍的 `lines`（含附表頁）
- 狀態（列先去空白）：含「資金貸與他人：無」→ loans `"none"`；含「資金貸與他人：請詳附表」→ `"table"`；都沒有 → `"unknown"`。背書保證同理（「為他人背書保證：無」／「為他人背書保證：請詳附表」）
- 背書保證列：在整列為「為他人背書保證」的標題列之後，以 `^\d+\s` 開頭且含 ≥5 個金額 token 的列為資料列；緊接的下一列若無金額 token 且不以「註」開頭，視為名稱續行，接到 `guarantor`（去空白後接合）。欄位順序：編號、背書保證者、被背書保證對象、關係、單一限額、本期最高餘額、期末餘額、實際動支、擔保金額、佔淨值比率、最高限額、三個 Y/N
- 資金貸與：整列為「資金貸與他人」的標題列之後、以 `^\d+\s` 開頭的列原文存 `loans_raw`
- 兩個狀態皆 `"unknown"` 且無列 → 回 None（記 `missing_tables` 的 `T9`）
- 3653 期望：loans_status `"none"`、guarantees_status `"table"`、3 列；第 1 列 no=0、guarantor「健策精密工業股份有限公司」、guaranteed「金利公司」、relation_code「(4)」、single_limit 4567472、max_balance 30000、ending_balance 30000、drawn None、collateral None、pct_of_net_worth 0.13、max_limit 9134944、Y／N／N；第 3 列 guarantor「金利公司」、guaranteed「南通健策公司」、pct_of_net_worth 5.49；`max_pct_of_net_worth` 5.49

#### 2.3.4 T10 股權質押＋前十大股東（年報，table 通道）

```python
@dataclass
class PledgeRow:
    name: str; reason: str | None; date: str | None; counterparty: str | None
    relation: str | None; shares: float | None; holding_pct: float | None
    pledge_pct: float | None; amount: float | None

@dataclass
class PledgeTable:
    status: str                  # "rows" | "none" | "external_reference" | "unknown"
    rows: list[PledgeRow]
    max_pledge_pct: float | None
    def to_dict(self) -> dict

def parse_pledges(tables, page_text: str) -> PledgeTable
```
- 只看「(三)股權質押資訊」之後的文字：有欄頭含「質押」與「股數」（去空白、去換行後比對）的表 → `"rows"`；否則其後 80 字內含「請參閱公開資訊觀測站」→ `"external_reference"`；含「無」→ `"none"`；都不成立 → `"unknown"`
- cell 內 `\n` 一律去除後再存；`-` → None
- 3653 2025 期望：status `"rows"`、1 列：name「恆山股份有限公司」、reason「質押」、date「114.08.11」、counterparty「兆豐國際商業銀行股份有限公司桃興分公司」、shares 1000000、holding_pct 11.36、pledge_pct 17.99、amount None；`max_pledge_pct` 17.99

```python
@dataclass
class ShareholderRow:
    name: str; is_representative: bool
    shares: float | None; pct: float | None
    spouse_shares: float | None; spouse_pct: float | None
    nominee_shares: float | None; nominee_pct: float | None

@dataclass
class TopShareholders:
    rows: list[ShareholderRow]
    relation_notes: list[str]
    def to_dict(self) -> dict

def parse_top_shareholders(tables, page_text: str) -> TopShareholders | None
```
- 表判定：第一列（去空白、去換行）含「本人」與「持有股份」
- 名稱 cell 含「代表人：」→ 拆成法人列（cell 第一段，取該列數字）與代表人列（`代表人：` 之後的名字，取**緊接的下一個名稱為 None 的列**的數字，`is_representative=True`）
- `relation_notes`：頁文字中「註：」之後、以 `\d+\.` 開頭的各列
- 3653 2025 期望：第 1 列 name「信昌國際實業股份有限公司」、shares 17460592、pct 11.90；第 2 列 name「趙宗信」、is_representative True、shares 2032002、pct 1.38、spouse_shares 10057；`is_representative=False` 的列共 10 列；relation_notes 3 條

#### 2.3.5 `TablesBundle` 擴充

加欄位 `guarantees_loans: GuaranteesLoans | None`、`pledges: PledgeTable | None`、`top_shareholders: TopShareholders | None`；`extract_tables` 加參數 `gov_anchors: dict | None = None`（預設 None 時兩個 T10 表皆缺，保持 1A 呼叫端相容）；T9 讀 `fs_anchors["fs_note_disclosure"]` 範圍的 `lines`。`missing_tables` 名稱加 `T9`、`T10_pledge`、`T10_top10`（`pledges.status=="unknown"` 視為缺）。

### 2.4 `sections.py`

白名單加 `ar_governance`、`ar_capital`（來自 `gov_anchors`；`build_sections` 加參數 `gov_anchors: dict | None = None`，None 時兩 key 為 `""`）。截斷規則同 1A。

### 2.5 `tasks.py`

每個 task 加 `skip_if_empty: list[str]`（非空且這些 key 全為空字串 → 跳過，記 `skipped_tasks`）；`tw_pipeline.py` 原本對 `tw_footnotes_quality` 的硬寫判斷改讀此欄（行為不變）。

```python
TW_PHASE1_TASKS = [
  # 1A 三條：input_keys 不變；skip_if_empty：cost=[]、financial=[]、footnotes=其 5 個 input_keys
  {"task_id": "tw_kam_analysis", "skill": "tw_kam_analysis",
   "input_keys": ["fs_audit_kam", "tables_json"], "skip_if_empty": ["fs_audit_kam"]},
  {"task_id": "tw_business_analysis", "skill": "tw_business_analysis",
   "input_keys": ["ar_letter", "ar_business", "tables_json"], "skip_if_empty": []},
  {"task_id": "tw_customer_supplier", "skill": "tw_customer_supplier",
   "input_keys": ["tables_json", "ar_market"], "skip_if_empty": []},
  {"task_id": "tw_governance_flags", "skill": "tw_governance_flags",
   "input_keys": ["tables_json", "ar_governance", "ar_capital"],
   "skip_if_empty": ["ar_governance", "ar_capital"]},
]
```
`ThreadPoolExecutor(max_workers=3)` 不變。

### 2.6 `tw_pipeline.py`
- 合併財報錨定改呼叫 `find_heading_sections(fs, FS_HEADING_ANCHORS, required={"fs_bs","fs_is"})`
- 年報加一次 `find_heading_sections(ar, GOVERNANCE_HEADING_ANCHORS, required=set())` → `gov_anchors`，傳給 `extract_tables`、`build_sections`；`anchors_summary` 併入 `gov_anchors`
- eval 的 `source_map` 補丁（1A §2.7 步驟 7）對新 4 個 task 同樣給 `tables_json`

### 2.7 `report.py`
主節加在 `## 3. 附註品質` 之後：`## 4. 關鍵查核事項`、`## 5. 業務與管理層敘述`、`## 6. 客戶與供應商`、`## 7. 公司治理警訊`。附錄 A 加 T9（兩個狀態＋背書保證表）、T10 質押表（含 status）、T10 前十大股東表；附錄 B 涵蓋新 anchor key 與新 missing 名稱。被跳過的 task 該節印「本節未執行：輸入資料不足（<task_id>）」。規則同 1A §2.8：每個新 render 函數有「有值」與「缺值」兩 fixture；缺 key 印「（skill 未回傳）」。

---

## 3. Skill 契約（`skills/tw/`；frontmatter 與共通規則同 1A §3：繁中、不做算術、`missing_tables` 內的表不得引用、Input 皆含選填 `retry_hint`）

### 3.1 `tw_kam_analysis`
- Input：`fs_audit_kam`（必填）、`tables_json`（必填）
- Instructions：逐項列出關鍵查核事項；說明為何是關鍵（依會計師原文）、會計師的因應程序；對照 `tables_json` 指出該事項連到哪個數字（例：收入截止 → T7b 營業收入、存貨評價 → T5 與 `writedown`）；不得推論查核意見以外的結論
- Output：
```json
{"matters": [{"matter": "", "why_key": "", "audit_response": "", "risk_area": "revenue|inventory|valuation|related_party|other"}],
 "linkage_to_numbers": [{"matter": "", "table_ref": "", "observation": ""}],
 "key_observations": [""], "insufficient_data": false}
```

### 3.2 `tw_business_analysis`
- Input：`ar_letter`（必填）、`ar_business`（必填）、`tables_json`（必填）
- Instructions：業務與產品摘要；管理層計畫（標明期間與是否可量測）；敘述 vs 數字：致股東報告書與業務章的量化宣稱逐條對照 `tables_json`（T7b、T8、T4），標明一致／不一致／無法核對
- Output：
```json
{"business_summary": "", "products": [{"name": "", "note": ""}],
 "management_plans": [{"plan": "", "horizon": "", "measurable": true}],
 "narrative_vs_numbers": [{"claim": "", "table_ref": "", "status": "consistent|inconsistent|unverifiable", "note": ""}],
 "key_observations": [""], "insufficient_data": false}
```

### 3.3 `tw_customer_supplier`
- Input：`tables_json`（必填，用 T8 與 `concentration`）、`ar_market`（選填）
- Instructions：客戶與供應商集中度（只引用 `concentration` 既有數字）、兩年度名次與占比變化（由 T8 兩年度欄位）、關係人客戶／供應商（`relation` 非「無」者）、議價力判斷與理由、`ar_market` 中的原料來源與供應狀況
- Output：
```json
{"customer_concentration": {"top1_pct": null, "top3_pct": null, "direction": "rising|stable|falling|unknown", "note": ""},
 "supplier_concentration": {"top1_pct": null, "top3_pct": null, "direction": "rising|stable|falling|unknown", "note": ""},
 "related_counterparties": [{"name": "", "kind": "customer|supplier", "relation": ""}],
 "bargaining_power": {"vs_customers": "strong|neutral|weak|unknown", "vs_suppliers": "strong|neutral|weak|unknown", "rationale": ""},
 "key_observations": [""], "insufficient_data": false}
```

### 3.4 `tw_governance_flags`
- Input：`tables_json`（必填，用 T10、T9）、`ar_governance`（選填）、`ar_capital`（選填）
- Instructions：質押（status、`max_pledge_pct`；比率 >30% 標 watch、>50% 標 alert——門檻寫在 skill 內，skill 只比較不計算）、前十大股東結構與 `relation_notes` 顯示的家族關係、董事會組成與獨立董事（`ar_governance`）、背書保證對象與佔淨值比率（T9 `max_pct_of_net_worth`）、`ar_capital` 中的增資、公司債、限制員工權利新股等資本行動
- Output：
```json
{"pledge": {"status": "rows|none|external_reference|unknown", "max_pledge_pct": null, "flag": "normal|watch|alert", "note": ""},
 "ownership": {"structure_note": "", "family_relations_note": "", "flag": "normal|watch"},
 "board": {"independence_note": "", "flag": "normal|watch|unknown"},
 "guarantees": {"note": "", "flag": "normal|watch|none_disclosed"},
 "capital_actions": [{"item": "", "note": ""}],
 "key_observations": [""], "insufficient_data": false}
```

### 3.5 `runtime/eval_runner.py` 的 `REQUIRED_KEYS` 加
```python
"tw_kam_analysis":      ["matters", "key_observations", "insufficient_data"],
"tw_business_analysis": ["business_summary", "narrative_vs_numbers", "insufficient_data"],
"tw_customer_supplier": ["customer_concentration", "supplier_concentration", "insufficient_data"],
"tw_governance_flags":  ["pledge", "ownership", "insufficient_data"],
```
### 3.6 `runtime/mock_outputs.json` 加四個 key，值為上述 Output 骨架填合理假資料

---

## 4. 測試與 fixture

- **真實財報 fixture**：producer `tests/fixtures/tw_equity/make_fs_fixture.py`（進版控）從 `tw_report/3653_2025Q4合併財報.pdf` 抽頁 2、3、5、6、10、11、12、14、22、29、31、46、47、51、55、64、67 → `fs_3653_pages.json`（`pdf_doc.to_json` 格式，含 `lines`；頁碼保留原頁碼）。測試讀 JSON，不依賴 PDF
- **年報 fixture 擴充**：`make_ar_fixture.py` 加抽頁 8、57、58、59、65，並改為輸出含 `lines` 的格式；重新產生 `ar_3653_pages.json`。1A 既有測試須仍通過
- **合成 fixture**：T9 資金貸與 `"table"` 狀態與 `loans_raw`；T10 質押 `"none"`／`"external_reference"` 兩種文字；`_line_opener` 假物件
- 必測（每條對應 §2 契約）：
  - `line_amounts`：`( 11,841,587 )`→-11841587、`($ 2,277)`→-2277、`$ 4,567,472`→4567472、`0.13%`→0.13、`-`→None、`3,048`→3048
  - `pdf_doc`：`lines` 由假 words 重組（y 差 ≤3 同列、x 排序）；`to_json`→`from_json` 等價；舊格式缺 `lines` → `[]`；兩 opener 頁數不同 → `ValueError`
  - `find_heading_sections`：真實 fs fixture 的 10 個 key 起頁等於 §2.2.2 表；p2–p3 目錄頁不被當起頁；`fs_note_inventory` 不錨到 p22 會計政策「(十四)存貨」；缺 required → `AnchorError`
  - 治理 key：真實年報 fixture 起頁等於 §2.2.3 表
  - §2.3.1 三個列通道解析器以真實 fs fixture 驗期望值；列通道回 None 時退回 table 通道（以 1A 合成 fixture 驗）
  - T9、T10 以真實 fixture 驗 §2.3.3／§2.3.4 期望值；合成 fixture 驗 `"none"`／`"external_reference"`／`loans_raw`
  - `concentration`：3653 T8 真實值 `top1_pct`（114 年度銷貨 22.82）；表缺 → 空 list
  - `skip_if_empty`：kam 輸入空 → `skipped_tasks` 含 `tw_kam_analysis`；1A footnotes 跳過行為不變
  - report：4 個新 render 函數各「有值／缺值」fixture；被跳過的 task 印未執行訊息；md 含 7 個 `## ` 主節與 2 個附錄
  - pipeline：真實年報＋真實財報 fixture 經 `_opener`／`_line_opener` 注入（或以 monkeypatch `pdf_doc.load_pdf` 回 fixture `PdfDoc`）、`run_agent` monkeypatch，產出 md 與 raw.json；raw.json 的 `missing_tables` 等於 §5 DoD-2 清單
- 全套測試指令：`./.venv/bin/python -m pytest -q`

---

## 5. 驗收（Phase 1B-1 DoD）

1. 全套測試通過，無新增穩定失敗
2. `python main.py 3653 --market tw-equity --dry-run` 以工作目錄的真實年報＋真實合併財報跑通，產出 md＋pdf＋raw.json；raw.json `missing_tables` 恰為 `["T1","T2","T3","T6"]`（個體財報未提供、年報無產銷量值表）；`consolidated_key_lines` 營業成本為 (11841587, 8912721)；`parent_cost_coverage` 為 None；報告含 7 個主節
3. 真實 LLM 跑（不加 `--dry-run`）**不在本 run 自動執行**：需使用者明示允許（既有約定：未經允許不打真實 API）

---

## 6. 開放問題與本 run 的假設（HITL 裁示點）

| # | 問題 | 本 run 假設 |
|---|---|---|
| Q1 | 列通道用 PyMuPDF（已裝在 `.venv`，1.27.2.2）。授權是 **AGPL-3.0**；本 repo 授權為 MIT。替代方案：pdfplumber `extract_words` 座標重組，實測數字有字距（`1 46,742 6 7,444`、`4 9 , 1 8 0`），須以「依金額格式合併 token」修正，相鄰的短數字有歧義 | 採 PyMuPDF，`requirements.txt` 加 `PyMuPDF>=1.27`。若本專案會對外散布或以網路服務提供，請改裁示用 pdfplumber 方案 |
| Q2 | 個體財報仍未取得 | T1–T3 維持 1A 合成 fixture；`parent_cost_coverage` 在真實跑為 None（`tw_cost_structure` 走 1A §3.1 的 `annual_report_only` 路徑） |
| Q3 | `tw_footnotes_quality`（1A）已輸出 `kam` 欄，與新 `tw_kam_analysis` 重疊 | 不改 1A skill；報告兩節並存。整併留到 1B-2 後再評估 |
| Q4 | 上位計畫寫 `tw_customer_supplier`「對接既有 `supply_chain_analysis`」 | 本 run 不對接（`supply_chain_analysis` 是 US 10-K skill，輸入不同）；只做以 T8 為主的獨立 skill |
| Q5 | 質押警示門檻（>30% watch、>50% alert） | 採用；門檻寫在 skill md，可日後調整 |
| Q6 | 2317／2454／2926 年報的質押與前十大股東版面不同（例：2317 只有「無股權質押之相對人為關係人之情形」文字） | 本 run 只以 3653 驗收；其他公司的差異由 `"unknown"`／缺表路徑承接，不另調校 |

---

## 7. Out of Scope（Phase 1B-1）
跨年比較與前一年輸入（1B-2）、OCR 備援（1B-2）、個體財報真實版面校正（等 PDF）、年報既有 key 改標題行錨定、T6 產銷量值、季度模式與法說會（1C）、MOPS 自動下載（1D）、修改 1A 三個 skill。
