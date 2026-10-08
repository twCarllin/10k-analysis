# Spec：台股財報分析 pipeline Phase 1B-2（`tw-equity`）跨年比較＋OCR 備援

> run_id：`2026-10-08-tw-equity-phase-1b2`。上位計畫：`specs/tw_equity_plan.md`（§6 Phase 1B，驗收「同一家公司兩個年度，報告含跨年差異」）。前序 Spec：`specs/tw-equity-phase-1a.md`（以下「1A §x」）、`spec/2026-10-08-tw-equity-phase-1b1.md`（以下「1B-1 §x」）。`specs/` 為 gitignored、只在工作目錄。
> 本 Spec 自足：不依賴對話；與上位計畫或前序 Spec 不同處，以本 Spec 為準。

---

## 0. 定位與前提

### 0.1 範圍（使用者 2026-10-08 裁示 Phase 1B 拆兩 run，本 run 為第二個）

①輸入檔加前一年度 ②前一年度跑同一套解析與 skill ③確定性跨年表格比對 ④既有 `cross_year_compare` skill 做跨年敘述比較 ⑤報告加跨年節 ⑥字型無法解碼頁（`(cid:NNNN)`）的 OCR 備援（Azure Document Intelligence，使用者 2026-10-08 裁示納入 1B）。驗收：3653 的 114（2025）與 113（2024）年度。

### 0.2 實測事實（2026-10-08）

| 項目 | 事實 | 處置 |
|---|---|---|
| `tw_report/3653_2024年報.pdf`（90 頁，113 年度） | 章節結構與 2025 年報相同（壹–陸）。17 頁字型無 ToUnicode 對照：p8、12、13、15–19、22、43、47、49、51、59、79、86、88，pdfplumber、pypdf、PyMuPDF 皆只得 `(cid:NNNN)` 或亂字 | 偵測亂碼頁（§2.2）；OCR 備援（§2.3） |
| 2024 年報受影響內容 | p51＝前十大股東表（T10_top10）；p79＝伍章首頁（`ar_mdna`、`ar_fin_position`、T7a 財務狀況比較表）；p86、p88＝風險事項部分頁 | 有 OCR 時可讀；無 OCR 時這些表／錨點記缺 |
| 2024 年報可讀內容 | p5 致股東報告書、p57– 業務、p68「二、市場及產銷概況」（在頁面第 348 字，超過 1A 頁首 300 字規則 → 1A `find_sections` 錨不到 required key `ar_market`）、p72 T8 進貨表、p73 T8 銷貨表、p80 T7b 財務績效表（113／112 年度）、p50「(三)股權質押資訊：無。」 | 年報錨點加標題行備援（§2.4） |
| 2024 年度合併財報 | 未提供 | 前一年度 `consolidated_fs_path` 為 null；`tw_kam_analysis` 依 `skip_if_empty` 跳過；KAM 不做跨年 |
| 既有 `runtime/tw_credit/adapters.py` | `AzureDIAdapter.extract()` 只回傳徵信用的「銷售量值表」產品清單；`MistralOCRAdapter.extract_pages()` 回傳整份文件逐頁 markdown、無表格結構。兩者皆不提供「指定頁的列＋表格」 | 新寫 `runtime/tw_equity/ocr.py`（2026-10-08 改：Mistral 為主，以 `MistralOCRAdapter.extract_pages` 處理抽出的子 PDF，見 §2.3b）；只 import tw_credit 的 `_load_azure_config`、`_default_http_post`、`_default_http_get`、`AdapterError`、`_DI_API_VERSION`，不改 tw_credit |
| `skills/common/cross_year_compare.md` | Input：`current_analysis`（必填 JSON）、`prior_analysis`（選填 JSON）；Output：`cross_checks`、`mgmt_credibility`、`mgmt_credibility_reason`、`quality_trend`、`overall_direction`、`insufficient_data`。`runtime/mock_outputs.json` 已有 `cross_year_compare` 條目；`eval_runner.REQUIRED_KEYS` 無此條目 | 直接使用，不改 skill 檔 |

### 0.3 不碰的既有檔案
`runtime/tw_credit/**`、`runtime/orchestrator.py`、`runtime/jp_*.py`、`runtime/report_writer.py`（只 import）、`skills/common/cross_year_compare.md`、`skills/tw/*.md`（1A、1B-1 的七個 skill）、`agents/analyst_agent.md`、`runtime/eval_runner.py`、`runtime/mock_outputs.json`。
允許改：`runtime/tw_equity/**`、`main.py`（只在 tw-equity 分支加 `--ocr` 傳遞與 help 文字）、`tw_equity_inputs/3653.json`、`tests/tw_equity/**`、`tests/fixtures/tw_equity/**`、`README.md`（tw-equity 段補跨年與 `--ocr` 說明）。

---

## 1. 輸入與 CLI

### 1.1 輸入檔加 `prior`（選填）

```json
{
  "ticker": "3653", "company_name": "健策精密工業股份有限公司", "fiscal_year": 2025,
  "annual_report_path": "tw_report/2025_3653_健策年報.pdf",
  "consolidated_fs_path": "tw_report/3653_2025Q4合併財報.pdf", "parent_fs_path": null,
  "prior": {
    "fiscal_year": 2024,
    "annual_report_path": "tw_report/3653_2024年報.pdf",
    "consolidated_fs_path": null, "parent_fs_path": null
  }
}
```

```python
@dataclass(frozen=True)
class PriorYearInputs:
    fiscal_year: int
    annual_report_path: Path
    consolidated_fs_path: Path | None
    parent_fs_path: Path | None
    @property
    def roc_year(self) -> int: ...

# TwEquityInputs 加欄位 prior: PriorYearInputs | None = None
```
- `prior` 缺或為 null → `None`（行為與 1B-1 完全相同）
- `prior.fiscal_year` 必須等於 `fiscal_year - 1`，否則 `ValueError`（訊息含兩個年度）
- `prior` 內必填：`fiscal_year`、`annual_report_path`；路徑規則同 1A §1.1（給了不存在的路徑 → `FileNotFoundError`）

### 1.2 CLI

```bash
python main.py 3653 --market tw-equity --dry-run          # 不發 LLM API；不呼叫 OCR
python main.py 3653 --market tw-equity --dry-run --ocr    # 不發 LLM API；亂碼頁呼叫 Azure DI
```
- `--ocr` 為 `store_true`，只在 tw-equity 分支傳給 `run_tw_equity_pipeline(..., ocr=args.ocr)`；其他 market 忽略
- `--dry-run` 只控制 LLM；OCR 只由 `--ocr` 控制（OCR 是付費外部 API，須明示開啟）

---

## 2. 模組契約（`runtime/tw_equity/`）

### 2.1 `inputs.py`：§1.1

### 2.2 `pdf_doc.py`：亂碼頁偵測與 OCR hook

```python
@dataclass
class PdfDoc:
    path: Path
    pages: list[Page]
    garbled_pages: list[int] = field(default_factory=list)   # 偵測到的亂碼頁
    ocr_pages: list[int] = field(default_factory=list)       # 已以 OCR 取代內容的頁

def is_garbled(page: Page) -> bool          # page.text 中 `(cid:\d+)` 出現 ≥20 次

OcrFn = Callable[[Path, list[int]], dict[int, Page]]   # 回傳 頁碼 → 取代用 Page

def load_pdf(path, *, cache_dir=None, _opener=None, _line_opener=None,
             ocr: OcrFn | None = None) -> PdfDoc
```
- 先照 1B-1 建 pages，再算 `garbled_pages`
- `ocr` 非 None 且 `garbled_pages` 非空 → 呼叫一次 `ocr(path, garbled_pages)`；回傳的每個 Page 取代原頁（`number` 保持原頁碼），該頁碼記入 `ocr_pages`；OCR 回傳缺某頁 → 該頁照下一條處理
- 未被 OCR 取代的亂碼頁：`text=""`、`lines=[]`、`tables=[]`（亂碼不得進入錨定與解析）
- `ocr` 例外（`AdapterError` 等）不吞：往上拋（給錯憑證是部署錯誤；呼叫端決定）
- 快取：無 OCR 時檔名同 1B-1（`<sha16>.json`）；有 OCR 時 `<sha16>.ocr.json`。兩者互不覆蓋。`garbled_pages`、`ocr_pages` 進 `to_json`／`from_json`（缺欄 → `[]`）。`_CACHE_VERSION` 加 1，並同步 1A／1B-1 的合成 fixture `version`（同 1B-1 item 1.1 裁決）

### 2.3 `ocr.py`：Azure DI 逐頁 adapter（新檔）

```python
class DiPageOcr:
    def __init__(self, *, _http_post=None, _http_get=None, _sleep=time.sleep): ...
    def __call__(self, path: Path, pages: list[int]) -> dict[int, Page]: ...
```
- 端點：`{di_endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version={_DI_API_VERSION}&pages={逗號清單}`；body `{"base64Source": <整份 PDF base64>}`；header `Ocp-Apim-Subscription-Key`（key 不得出現在 URL）
- 202 → 輪詢 `Operation-Location`（間隔 2 秒、上限 180 秒；`_sleep` 為測試注入點）；200 → 直接解析；其他 → `AdapterError`（訊息不含 endpoint／key）
- 轉換（每個 `analyzeResult.pages[i]`）：`Page.number`＝`pageNumber`；`Page.lines`＝`lines[].content`（DI 原順序，去頭尾空白、丟空列）；`Page.text`＝`"\n".join(lines)`；`Page.tables`＝`analyzeResult.tables` 中 `boundingRegions[0].pageNumber` 為該頁者，依 `rowCount`×`columnCount` 建二維 list、以 `cells[].rowIndex／columnIndex／content` 填入（未填格為 `None`；`rowSpan`／`columnSpan` 只填左上格）
- 設定缺 `di_endpoint` 或 `di_key` → 建構時 `AdapterError("Azure DI 設定缺漏")`

### 2.3b `ocr.py`：Mistral OCR 逐頁 adapter（主要 OCR；使用者 2026-10-08 裁示）

> 背景：item 2.3 以 `DiPageOcr` 真實呼叫 Azure DI 回 HTTP 403（憑證或資源權限問題，主 flow 本地核對 URL／header 寫法與 tw_credit 一致）。使用者裁示改用 `config.json` 既有的 Azure Mistral OCR（`azure.mistral_ocr_endpoint`／`mistral_ocr_key`／`mistral_ocr_model`）。`DiPageOcr` 保留（已實作與測試），作為備援。

```python
class MistralPageOcr:
    def __init__(self, *, _adapter=None): ...          # 預設 runtime.tw_credit.adapters.MistralOCRAdapter()
    def fetch(self, path: Path, pages: list[int]) -> dict[int, str]: ...   # 頁碼 → 原始 markdown
    def __call__(self, path: Path, pages: list[int]) -> dict[int, Page]: ...
def markdown_to_page(number: int, markdown: str) -> Page
```
- `fetch`：以 PyMuPDF 把 `pages`（1-indexed、依給定順序）抽成暫存 PDF → `MistralOCRAdapter.extract_pages(暫存路徑)` → 回傳 list 第 i 個對應 `pages[i]`；回傳頁數與 `pages` 不同 → `AdapterError`；暫存檔用完即刪（例外時也刪）。不改 `runtime/tw_credit/adapters.py`
- `markdown_to_page`：
  - 連續以 `|` 開頭的列為一個表格區塊；分隔列（`^\|?\s*:?-{3,}`）略過；其餘列依 `|` 切 cell、去頭尾空白、空字串 → `None`；每個區塊成為 `Page.tables` 的一張表
  - `Page.lines`：每個非空列去掉 markdown 標記（行首 `#{1,6}`、`>`、列表標記 `-`／`*`——三者都須後接空白才算標記，例如 `-5.2%` 的負號必須保留；與成對的 `**`；主 flow 2026-10-08 依 reviewer 🟡 修正措辭），表格列以單一空白接合其 cell；去頭尾空白、丟空列
  - `Page.text`：`"\n".join(lines)`
  - 圖片連結（`![...](...)`）整列丟棄
- `tw_pipeline` 在 `ocr=True` 時用 OCR 鏈：先 `MistralPageOcr`；其 `AdapterError` → 改用 `DiPageOcr`；兩者皆失敗 → 拋 `AdapterError`，訊息含兩個 provider 的失敗原因（不含 endpoint／key）
- **OCR 數字檢查**（`cross_year.py` 外加、確定性）：`ocr_checks(doc: PdfDoc, bundle: TablesBundle, anchors: dict) -> list[dict]`（主 flow 2026-10-08 裁決加 `anchors`：年報錨點與治理錨點合併的 dict）——`anchors["ar_fin_position"]` 範圍與 `doc.ocr_pages` 有交集 → 檢查 T7a；`anchors["ar_top10"]` 範圍與 `doc.ocr_pages` 有交集 → 檢查前十大股東；對 OCR 取代頁所產生的表：①T7a 每列 `|current − prior − diff| ≤ 1`；②前十大股東 `is_representative=False` 列的 `pct` 合計 ≤ 100。結果放入 raw.json `ocr_checks`、附錄 B 列出未通過者（「OCR 數字未通過檢查」），不中斷

### 2.4 `doc_anchor.py`：年報標題行備援

```python
AR_HEADING_FALLBACK: dict[str, HeadingAnchor]
def find_annual_report_sections(doc: PdfDoc, *, required: set[str]) -> dict[str, PageRange | None]
```
- 步驟：①`find_sections(doc, ANNUAL_REPORT_ANCHORS, required=set(), order=list(ANNUAL_REPORT_ANCHORS))` ②對結果為 None 且在 `AR_HEADING_FALLBACK` 的 key，以 `find_heading_sections(doc, {該 key: …}, required=set())` 取起頁 ③合併所有 key 的起頁後，**重新計算終頁**（規則同 1A：下一個起頁較大的 key 的起頁 − 1，最後一個到末頁）④`required` 缺 → `AnchorError`
- `AR_HEADING_FALLBACK`：`ar_market`＝`HeadingAnchor(["市場及產銷概況"], True)`、`ar_mdna`＝`HeadingAnchor(["財務狀況及財務績效之檢討分析"], True)`、`ar_fin_position`＝`HeadingAnchor(["財務狀況"], True, after="ar_mdna")`、`ar_fin_performance`＝`HeadingAnchor(["財務績效"], True, after="ar_mdna")`。關鍵字若無法命中期望頁，writer 以 fixture 為準調整並記錄；期望起頁不可改
- 期望：2025 年報結果與 1B-1 完全相同（既有 key 皆由步驟①命中）；2024 年報（未 OCR）`ar_market` 起頁 68；2024 年報（p79 以 OCR fixture 取代）`ar_mdna`、`ar_fin_position` 起頁 79、`ar_fin_performance` 起頁 80
- `tw_pipeline` 當年度以 `required=_AR_REQUIRED` 呼叫；前一年度以 `required=set()` 呼叫（前一年度缺錨不中斷，缺的 key 記入前一年度的 `anchors_summary` 為 None）

### 2.5 `cross_year.py`：確定性跨年比對（新檔，無 LLM）

```python
def build_cross_year(current: TablesBundle, prior: TablesBundle, *,
                     current_roc: int, prior_roc: int) -> dict
```
回傳（全部 key 必有；資料缺時為空 list 或 None）：
```json
{
  "years": {"current": 114, "prior": 113},
  "fin_performance_series": [{"label": "營業收入", "values": {"112年度": 12062664, "113年度": 14278187, "114年度": 20275577}}],
  "overlap_checks": [{"table": "T7b", "label": "營業收入", "year": "113年度", "current_doc": 14278187, "prior_doc": 14278187, "match": true}],
  "customer_concentration_series": {"T8_sales": [{"label": "112年度", "top1_pct": 15.37}], "T8_purchase": []},
  "top_shareholders_change": [{"name": "", "current_pct": null, "prior_pct": null, "delta_pct": null, "status": "both|new|exited"}],
  "pledge_change": {"current_status": "rows", "prior_status": "none", "current_max_pct": 17.99, "prior_max_pct": null}
}
```
- `fin_performance_series`：合併兩份 T7b（當年度表含 current／prior 年、前一年度表含其 current／prior 年）依 label、年度標籤合成序列；同一年度兩份皆有值時以當年度文件為準
- （主 flow 2026-10-08 裁決）T7b 任一邊為 None → `fin_performance_series` 與 T7b 的 overlap 為空；T7a 任一邊為 None → 只少 T7a 的 overlap，其餘照常
- （主 flow 2026-10-08 裁決，真實 OCR 實測）1A `parse_two_year_table` 的表頭年度標籤比對改為去除空白後比對（Mistral OCR p79 表頭為「113 年度」）
- `overlap_checks`：T7a、T7b 中兩份文件都揭露的同一年度同一列，`match`＝兩值差絕對值 ≤1（千元捨入）；用於偵測重編
- `customer_concentration_series`：合併兩份 `concentration`（1B-1 §2.3.2），同 label 以當年度為準，依年度升冪
- `top_shareholders_change`：以 `is_representative=False` 的列、名稱（去空白）為鍵；`delta_pct` 四捨五入 2 位；一邊缺 → `new`／`exited`
- `pledge_change`：任一邊 `pledges` 為 None → 對應欄為 `"unknown"`／None
- 本 dict 放入當年度 `TablesBundle.to_dict()` 之外的獨立欄位（見 §2.6），不改 `TablesBundle`

### 2.6 `tw_pipeline.py`：兩年度

```python
def run_tw_equity_pipeline(ticker, *, dry_run=False, base_dir=None, ocr: bool = False) -> Path
```
- 把 1B-1 的 Phase 2–7（載入、錨定、抽表、組段、跑 skill、eval loop）抽成 `_analyze_year(...) -> YearResult`（`YearResult` 含 bundle、sections、anchors_summary、skill_results、eval_results、skipped_tasks、garbled_pages、ocr_pages），當年度與前一年度各呼叫一次；當年度行為與 1B-1 相同
- `ocr=True` → 兩個年度的 `load_pdf` 都傳 `ocr=DiPageOcr()`；`ocr=False` → 不傳
- 有 `prior` 時，另跑：①`build_cross_year` ②`run_agent("analyst_agent", "cross_year_compare", {"current_analysis": json.dumps({**current.skill_results, "_cross_year_tables": cross_year}, ensure_ascii=False), "prior_analysis": json.dumps(prior.skill_results, ensure_ascii=False)}, task_label="cross_year_compare")`；例外降級為 `{"error": …}`，不中斷
- 前一年度 skill 範圍：與當年度相同的 `TW_PHASE1_TASKS`，同樣套用 `skip_if_empty`（前一年度無財報 → `tw_kam_analysis`、`tw_footnotes_quality` 依輸入跳過）。見 §6 Q2
- 無 `prior` → 不呼叫 `build_cross_year`、不呼叫 `cross_year_compare`；輸出與 1B-1 相同（第 8 節印「本節未執行：未提供前一年度」）
- 每階段印 `[tw-equity Phase n]`，前一年度印 `[tw-equity prior Phase n]`

### 2.7 `report.py`
- 主節加 `## 8. 跨年比較`：`cross_year_compare` 的 `cross_checks`（逐條 dimensions／finding／implication／direction）、`mgmt_credibility`＋理由、`quality_trend`、`overall_direction`；skill 失敗印失敗訊息；無前一年度印未執行訊息
- 加 `## 附錄 C：跨年表格比對`：`fin_performance_series` 表（列＝label、欄＝年度升冪）、`overlap_checks`（只列 `match=false` 者；全部相符印「兩份文件重疊年度數字一致」）、客戶集中度序列、前十大股東變動、質押變動
- 附錄 B 加：各年度 `garbled_pages`、`ocr_pages`；前一年度錨定結果與 `missing_tables`
- raw.json 加 `prior`（前一年度 bundle、anchors_summary、skill_results、skipped_tasks、garbled_pages、ocr_pages）、`cross_year`、`cross_year_compare`；無前一年度時三者為 None
- 規則同 1A §2.8：文字過 `tone_filter`、cell 過 `_escape_md_cell`、缺 key 印「（skill 未回傳）」；每個新 render 函數有「有值」與「缺值」兩 fixture

---

### 2.8 主 flow 2026-10-08 補充（task-decomposer 拆分時提出，主 flow 同意）
- `pdf_doc.apply_ocr_policy(doc: PdfDoc, ocr: OcrFn | None) -> PdfDoc`：§2.2 的亂碼偵測、OCR 取代與清空規則抽成此函式，`load_pdf` 內呼叫；測試可直接對 fixture `PdfDoc` 呼叫
- `DiPageOcr.fetch(path, pages) -> dict`：回傳原始 `analyzeResult`；`__call__` ＝ `fetch` ＋ §2.3 轉換。§4 OCR 回應 fixture 的真實分支以 `fetch` 取得
- `ocr.py` 以模組層名稱呼叫 `_load_azure_config`（`from runtime.tw_credit.adapters import _load_azure_config` 後以模組屬性存取），測試以 monkeypatch 注入假設定

## 3. Skill
不新增、不修改 skill。`cross_year_compare` 不經 eval loop（`REQUIRED_KEYS` 無此條目；US pipeline 亦未評）。dry-run 回 `mock_outputs.json` 既有 `cross_year_compare` 條目。

---

## 4. 測試與 fixture

- **2024 年報 fixture**：producer `tests/fixtures/tw_equity/make_ar2024_fixture.py` 從 `tw_report/3653_2024年報.pdf` 抽頁 3、4、5、50、51、57、68、72、73、79、80 → `ar2024_3653_pages.json`（含 `lines`、保留原頁碼；p51、p79 為亂碼原樣）
- **OCR 回應 fixture**（2026-10-08 改：使用者裁示改用 Mistral，真實回應存 `mistral_3653_2024_p51_p79.json`，形狀為 `{"_meta": …, "pages": {"51": <markdown>, "79": <markdown>}}`，producer `make_mistral_fixture.py`；下列 DI fixture 描述作廢）：`di_3653_2024_p51_p79.json`，形狀為 DI `analyzeResult`（`pages[].pageNumber／lines[].content`、`tables[].rowCount／columnCount／cells[]`）。來源見 §6 Q1：經使用者允許時為一次真實 DI 呼叫的回應（去除 key、endpoint 後存檔，producer `make_di_fixture.py` 進版控）；未允許時為依 2025 年報同章節版面手寫的合成回應，檔頭註明「合成」
- 必測（每條對應 §2 契約）：
  - inputs：`prior` 缺／null → None；年度不連續 → `ValueError`；`prior` 路徑不存在 → `FileNotFoundError`
  - `is_garbled`：2024 fixture p51 為 True、p50 為 False
  - `load_pdf`：無 ocr → p51／p79 的 text／lines／tables 皆空、`garbled_pages` 含 51、79、`ocr_pages` 空；假 ocr → 取代、`ocr_pages` 等於回傳頁；ocr 拋例外 → 往上拋；兩種快取檔名互不覆蓋
  - `DiPageOcr`：202＋輪詢成功、200 直接、4xx → `AdapterError`；URL 含 `pages=51,79` 且不含 key；表格 cell 依索引落位、span 只填左上
  - `find_annual_report_sections`：2025 fixture 結果與 1B-1 相同；2024 fixture（無 OCR）`ar_market`=68；2024 fixture＋OCR fixture → `ar_mdna`／`ar_fin_position`=79、`ar_fin_performance`=80
  - `build_cross_year`：真實 2025 fixture＋2024 fixture 的 T7b → `fin_performance_series` 營業收入三年值 {112年度: 12062664, 113年度: 14278187, 114年度: 20275577}；113 年度 `overlap_checks` 營業收入 `match=true`；合成差異 → `match=false`；前十大股東 new／exited／both；質押 rows vs none
  - pipeline：兩年度 fixture 注入、`run_agent` monkeypatch → raw.json 有 `prior`、`cross_year`、`cross_year_compare`；前一年度 `skipped_tasks` 含 `tw_kam_analysis`；無 `prior` 時三者 None、第 8 節印未執行；`cross_year_compare` 拋例外 → 不中斷、第 8 節印失敗
  - main：`--ocr` 傳到 pipeline（monkeypatch 驗參數）；未給 `--ocr` → `ocr=False`
  - report：第 8 節與附錄 C 各 render 函數「有值／缺值」fixture；md 含 8 個主節與 3 個附錄
- 全套測試指令：`./.venv/bin/python -m pytest -q`

---

## 5. 驗收（Phase 1B-2 DoD）

1. 全套測試通過，無新增穩定失敗
2. `tw_equity_inputs/3653.json` 加 `prior`（§1.1）。`python main.py 3653 --market tw-equity --dry-run`（不加 `--ocr`）以真實兩份年報＋2025 合併財報跑通：raw.json `prior.garbled_pages` 含 51、79、`prior.ocr_pages` 為空；`cross_year.fin_performance_series` 營業收入有 112／113／114 三年值；`overlap_checks` 113 年度營業收入 `match=true`；報告含 8 個主節與 3 個附錄
3. （§6 Q1 經使用者允許才執行）`python main.py 3653 --market tw-equity --dry-run --ocr`：`prior.ocr_pages` 等於 `prior.garbled_pages`（17 頁）；前一年度 T7a、T10_top10 不在 `missing_tables`
4. 真實 LLM 跑不在本 run 執行（需使用者明示允許）

---

## 6. 開放問題與本 run 的假設（HITL 裁示點）

| # | 問題 | 本 run 假設 |
|---|---|---|
| Q1 | Azure DI 是付費外部 API。設計依 DI `prebuilt-layout` 2024-11-30 文件，尚未以真實回應驗證；既有約定為「未經允許不打真實 API」 | **使用者 2026-10-08 裁示：(a)、(b) 皆允許；DI 回 403 後再裁示改用 Azure Mistral OCR，(a)、(b) 兩次真實呼叫皆授權（改送 Mistral）。** 原文：請使用者裁示是否允許：(a) 在 item 1 呼叫一次 DI（只送 2024 年報 p51、p79，取回應存成 fixture），以真實回應開發與測試；(b) 收尾時跑 DoD-3（17 頁）。未允許 → fixture 用合成回應、DoD-3 不跑，OCR 路徑的真實正確性留待使用者日後自行執行 `--ocr` |
| Q2 | 前一年度跑完整 skill 集，真實 LLM 跑時 LLM 呼叫數約為兩倍 | 採用（`cross_year_compare` 需要兩年度的分析結果）。dry-run 不受影響 |
| Q3 | 2024 年度合併財報未提供 | KAM、T4、T5、T9 不做跨年；前一年度這些表記缺 |
| Q4 | `cross_year_compare` 是 US 共用 skill，其 Instructions 以 10-K 維度（MD&A、Risk、Business）撰寫 | 不改 skill；tw 的維度名稱以 skill_results 的 task_id 呈現。若真實跑效果不佳，下一 run 再評估 tw 專用跨年 skill |
| Q5 | 當年度年報錨定加了標題行備援（§2.4），屬 1A 行為的擴充 | 只對步驟①結果為 None 的 key 生效；2025 年報結果須與 1B-1 完全相同（測試鎖定） |

---

## 7. Out of Scope
KAM／附註的跨年（缺 2024 財報）、個體財報、tw 專用跨年 skill、季度模式（1C）、MOPS 自動下載（1D）、Google Document AI、OCR 結果的人工校對介面。
