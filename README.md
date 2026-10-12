# Multi-Agent Investment Research Pipeline (US + JP + TW)

多市場財報分析 pipeline，使用 multi-agent + skill 架構：

- **US**：SEC EDGAR 10-K / 10-Q + Yahoo Finance earnings call transcript（[Stagehand](https://github.com/browserbase/stagehand) LOCAL 模式）
- **JP**：EDINET 有価証券報告書（yuho）/ 半期報 / 臨時報 + TDNET 適時開示（決算短信 PDF 解析）+ logmi 法說會逐字稿
- **TW**（`--market tw-equity`）：年報＋合併財報 PDF → 三表帳本、勾稽、指標與變動歸因、年報章節解析、會計問答

各 pipeline 共用 orchestrator / eval loop / report writer 底層，互不干擾。

輸出繁體中文 Markdown + PDF 報告，按公司分資料夾（`data/output/{TICKER}/`）。

US 輸出範例：`INTC_20260425_183226_report.pdf`
JP 輸出範例：`6315_20260517_1639_jp_report.pdf`（TOWA FY2026 Q4 決算短信分析）

## Python Version
3.13.12

## Changelog

- **2026-10** — TW pipeline（`--market tw-equity`）：年報／財報解析、三表帳本與勾稽（前 100 大 98/101 通過）、金控 fh schema、30 項指標與變動歸因、FY 損益／TTM、批次 runner、年報三章節解析、會計問答（`runtime.tw_equity.qa`）。
- **2026-05-17** — JP pipeline Phase 1A–1C：EDINET 有報 / 半期報 / 臨時報、jpcrp iXBRL 解析、7 個 jp_* narrative skill、TDNET scraper（決算短信 PDF 用 markitdown 抽 key_metrics / segment / forward_guidance）、logmi Stagehand adapter、watch / event 模式。報告按公司分子目錄。
- **2026-05-01** — 新增 earnings call transcript 抓取（Stagehand LOCAL 模式 + Yahoo Finance）與 `transcript_analysis` skill。報告章節重排，transcript 三節置頂。
- **2026-04-28** — 新增 `supply_chain_analysis` 與 `competitor_mapping` skill。
- **2025-04-25** — CLI 自動推算 prior year。新增「評價趨勢判斷」🟢🟡🔴 紅綠燈。`mdna_analysis` 加 `momentum` 欄位。

## To Do
- 利用程式和 eval 降低對模型的依賴程度

## Quick Start

```bash
# 1. Python 環境
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install pango  # PDF 生成需要

# 2. Node 環境（transcript 抓取用，首次 clone 需要）
#    需要 Node ≥ 20.19 或 ≥ 22.12（Stagehand v3 engines 要求）
cd runtime/transcript_scraper/node
npm install
npx playwright install chromium
cd ../../..

# 3. 設定 API Key
cp config.example.json config.json
# 編輯 config.json 填入 anthropic_api_key
# 若要跑 JP pipeline，再填 edinet_api_key（見下方「API Key 申請」）

# 4a. 美股執行（10-K 年報，自動比對前一年）
python main.py HWM 2025

# 4b. 美股 10-Q 季報（自動比對前期 + 抓 earnings call transcript）
python main.py HWM 2025 --filing-type 10-Q --quarter Q1

# 4c. 日股 yuho（FY2025 = 結束於 2025/3 的會計年度）
python main.py 6315 2025 --market jp

# 4d. 日股 FY2026 Q4 速報（yuho 未發時自動 fallback TDNET 決算短信）
python main.py 6315 2026 --market jp --quarter Q4

# 4e. 台股（先準備 tw_equity_inputs/<ticker>.json 與 PDF，見下方「台股」）
python main.py 2330 --market tw-equity
```

## API Key 申請

| API | 用途 | 收費 | 申請網址 |
|---|---|---|---|
| **Anthropic** | LLM（兩條 pipeline 都需要） | 按 token 計費 | https://console.anthropic.com/ |
| **EDINET（日股必填）** | 抓取日本 EDINET 有報 / 半期報 / 臨時報 metadata + ZIP | 免費 | https://api.edinet-fsa.go.jp/api/auth/index.aspx |
| SEC EDGAR | 抓取美股 10-K / 10-Q | 免費，**無需 key**，僅需 User-Agent header | — |
| TDNET（日股決算短信） | 從 release.tdnet.info scrape | 免費，**無需 key**，僅需 polite UA | — |
| logmi Finance | 日股法說會逐字稿 | 免費，**無需 key**（需 Stagehand 用 Anthropic API 解析網頁） | — |
| Azure（台股選用） | Document Intelligence OCR、Mistral OCR（`--ocr` 時才用） | 付費 | https://portal.azure.com/ |

台股 PDF 解析本身（pdfplumber）不需 key；只有 `--ocr` 會打上面的付費 API。

**日股 EDINET API key 申請流程**（5 分鐘內可拿到）：

1. 到 https://api.edinet-fsa.go.jp/api/auth/index.aspx
2. 填入 e-mail + 用途說明（個人研究即可）
3. 收驗證信 → 設密碼 → 取得 Subscription-Key
4. 填進 `config.json` 的 `edinet_api_key` 欄位
5. 驗證：
   ```bash
   curl "https://api.edinet-fsa.go.jp/api/v2/documents.json?date=2026-05-15&type=2&Subscription-Key=YOUR_KEY" | head -c 200
   # 應該回傳 JSON metadata
   ```

**J-Quants API**（股價 / 財務 statements）：**本專案不使用**。財務 5 年表從 EDINET 有報內含的 iXBRL instance 自抽，不需付費。

## 設定檔

```json
{
  "anthropic_api_key": "sk-ant-...",
  "edgar_user_agent": "10k-research your-name@example.com",
  "edinet_api_key": "your-edinet-api-key",
  "azure": { "...": "台股用，欄位見 config.example.json" },
  "model": "claude-sonnet-4-5",
  "max_tokens": 4096,
  "max_tokens_by_skill": {
    "risk_analysis": 8192,
    "mdna_analysis": 8192,
    "cross_year_compare": 8192,
    "insight_synthesis": 8192,
    "transcript_analysis": 8192
  }
}
```

台股 OCR 另在 `azure` 區塊加 `di_endpoint`／`di_key`（Azure Document Intelligence）與 `mistral_ocr_endpoint`／`mistral_ocr_key`。

## CLI 用法

### 美股（SEC，預設 `--market sec`）

```bash
# 完整分析（前期自動推算）
python main.py <TICKER> <YEAR>

# 10-Q 季報（Q1 比對 10-K，Q2+ 比對前一季）
python main.py <TICKER> <YEAR> --filing-type 10-Q --quarter Q1

# 手動覆蓋前期年份
python main.py HWM 2025 --prior-year 2022

# 指定本地檔案
python main.py HWM 2025 --file ./data/cache/htm/HWM_2025_10K.htm

# 只重跑特定 agent（其餘從快取載入）
python main.py HWM 2025 --only business,risk

# 清除 checkpoint 重新開始
python main.py HWM 2025 --clean

# 不發 API，用 mock 結果測試流程
python main.py HWM 2025 --dry-run
```

### 日股（EDINET / TDNET / logmi，加 `--market jp`）

```bash
# yuho（年度）：python main.py <JPX_CODE> <FY_END_YEAR> --market jp
python main.py 6315 2025 --market jp                    # FY2025/3 yuho (TOWA)

# 半期報：--quarter Q2
python main.py 6315 2025 --market jp --quarter Q2

# 速報（Q1 / Q3）或 yuho 未發時的 Q4：自動 fallback TDNET 決算短信 + PDF 解析
python main.py 6315 2026 --market jp --quarter Q4       # FY2026/3 速報（5/11 發）
python main.py 6315 2025 --market jp --quarter Q1       # FY2025/3 Q1 速報

# 單一 rinji（臨時報告書）分析
python main.py 6315 --market jp --event-doc-id S100W8RH

# TDNET watch 模式（cron-friendly，抓 watchlist 增量公告）
python main.py --market jp --tdnet-watch 6315,7203,9984 --since-minutes 30

# logmi 法說會逐字稿分析
python main.py 6315 --market jp --analyze-call
```

### 台股（`--market tw-equity`）

`runtime/tw_equity/`，與美股／日股並列的 market adapter，輸入為年報＋財報 PDF。

```bash
python main.py 3653 --market tw-equity              # 真跑（LLM 走 agent_runner 既有 provider）
python main.py 3653 --market tw-equity --dry-run    # 不發 API，skill 回 mock_outputs.json 的 tw_ 條目
python main.py 3653 --market tw-equity --ocr        # 亂碼頁改走 OCR（付費外部 API，須明示開啟）
```

- ticker 必填；`year` 位置參數在 tw-equity 忽略（年度由輸入檔決定）。
- 輸入檔 `tw_equity_inputs/<ticker>.json`：

```json
{
  "ticker": "2330",
  "company_name": "台灣積體電路製造股份有限公司",
  "fiscal_year": 2025,
  "group": "industrial",
  "annual_report_path": "tw_report/2330_2025年報.pdf",
  "consolidated_fs_path": "tw_report/2330_2026Q2財報.pdf",
  "fs_period": "2026H1",
  "parent_fs_path": null,
  "fy_consolidated_fs_path": "tw_report/2330_2025Q4合併財報.pdf",
  "fy_fs_period": "FY2025"
}
```

  repo 只附範例 `tw_equity_inputs/2330.json`、`3653.json`；其他公司的輸入檔與 `tw_report/` 下的 PDF 不進 git，請自行準備（PDF 可從公開資訊觀測站下載）。
  `ticker`、`company_name`、`fiscal_year`（西元年）、`annual_report_path` 必填；`group` 為 `fh`（金控）或 `bank`（銀行）時走金控三表 schema，其他值或省略走工業流程；`fy_consolidated_fs_path`／`fy_fs_period` 選填，提供時可問全年財報問題。`consolidated_fs_path`／`parent_fs_path` 可為 `null` 或省略，但給了路徑而檔案不存在會報 `FileNotFoundError`。輸入驗證失敗時印 `[tw-equity] <訊息>` 並以 exit 1 結束。
- **跨年比較（Phase 1B-2）**：輸入檔可加選填 `prior`（`fiscal_year` 須為前一年、`annual_report_path` 必填，`consolidated_fs_path`／`parent_fs_path` 可省略）。有 `prior` 時前一年度另跑一次分析，報告多出第 8 節「跨年比較」與附錄 C；無 `prior` 時第 8 節印「本節未執行：未提供前一年度」。
- 合併財報三表逐列解析為標準化帳本（`raw.json` 的 `bundle.statements`），含勾稽結果（附錄 D）。
- 帳本衍生 30 項指標與 8 組變動歸因（附錄 E、`raw.json` 的 `bundle.metrics`）。
- **`--ocr`**：年報中的亂碼頁（`(cid:N)` 字元過多）預設清空並記入附錄 B；加 `--ocr` 才會呼叫 OCR（Mistral 為主、失敗改 Azure DI），屬付費外部 API，預設關閉。
- **年報三章節結構化解析**（`runtime/tw_equity/ar_sections.py`，`raw.json` 的 `bundle.ar_cashflow`／`ar_contracts`／`ar_special`，解析失敗記 `ar_sections_error`，不影響其他表）：
  - 現金流量節：表 A（實際數）、表 B（未來一年預估數）、營業／投資／籌資說明原文；`arith_ok` 驗算表 A（期初＋各項流量＝期末，容差 2 仟元）；`basis` 比對帳本現金判斷是否為合併數字（`consolidated`／`non_consolidated`／`unknown`）。新版年報常只有比率表與表 B，此時 `actual` 為 null、`arith_ok` 為 null。
  - 重要契約節：每列契約性質、當事人、起訖日期、主要內容、限制條款；年報寫「無」時 status 為 `none`。
  - 特別記載事項：關係企業、私募、其他必要補充說明、證交法第 36 條重大影響事項 4 個子項的 status 與原文。
  - 解析不了的章節記 `failed`／`not_found` 與 reason，不猜數字。101 家中仍有部分公司解析未通過。
- **會計問答**（`runtime/tw_equity/qa.py`，規則見 `skills/tw/tw_accounting_qa.md`）：

```bash
python -m runtime.tw_equity.qa --ticker 3653 --ask "有哪些重要契約？"          # 模板答案，不打 API
python -m runtime.tw_equity.qa --ticker 3653 --ask "FCF 為什麼變動？" --llm    # LLM 寫答案，程式核對數字
python -m runtime.tw_equity.qa --ticker 2454 --ask "2025 年 FCF" --period fy   # 期間：auto（依用詞）／h1／fy
```

  年報章節主題：`ar:cashflow`（現金流動性分析、未來一年預估）、`ar:contracts`、`ar:special`；答案附頁碼，數字只准引用事實包內的值。章節 failed／not_found 時不加該主題。
- **批次**（不呼叫 LLM，每家輸出固定 schema JSON，單家失敗不中斷）：

```bash
python -m runtime.tw_equity.batch                    # 全部 tw_equity_inputs/*.json
python -m runtime.tw_equity.batch --tickers 2330,3653 --out data/output/batch/test
```

- **驗收工具**（只讀快取，不打 OCR／API；需要本地有對應的輸入檔與 PDF）：

```bash
python -m runtime.tw_equity.fs_acceptance --all70        # 三表帳本勾稽，SUMMARY conform=98/101
python -m runtime.tw_equity.ar_acceptance --all101 --gold # 年報三章節，含金標 10 家比對
```

- **Phase 1A 限制**：解析層只用 pdfplumber（無 DI／OCR 備援）；財報缺檔時 T1–T5 列入 `missing_tables`，並在報告附錄明示；T6（產銷量值）為選配，錨不到同樣記 `missing_tables`；T9（背書保證／資金貸與）延到 Phase 1B。

**會計年度命名**：「FY2026」= 結束於 2026 年的會計年度，預設 fiscal year end = 3/31（大多數日企）。FY2026 Q1 = 2025/4–6、Q4 = 2026/1–3（年度結尾）。

## Pipeline 架構

```
                         main.py
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
      sec_data_fetcher doc_converter  section_splitter
         (EDGAR API)   (markitdown)   (TOC-guided + LLM fallback)
              │            │            │
              └────────────┼────────────┘
                           ▼
                     orchestrator.py
                           │
     ┌─────── Phase 1 (平行) ───────────────────────────┐
     │ business │ competitor_mapping │ risk │ mdna       │
     │ governance │ fn_* x8 │ terms_glossary             │
     │ supply_chain（10-K + Q1）                         │
     └───────────────────────────────────────────────────┘
                           │
     ┌─────── Phase 2 (序列) ─────────────────────┐
     │ 2a: financial (XBRL+FS+fn)               │
     │ 2b: segment_trend (XBRL+biz+mdna)        │
     │ 2c: three_statement_cross (financial+XBRL)│
     └──────────────────────────────────────────┘
                           │
     ┌─────── Phase 3 ────────────────────────────┐
     │ 3a: unusual_operations                     │
     │ 3b: rerate（3 條件平行）                     │
     │     ├── rerate_structure (segment_trend)   │
     │     ├── rerate_quality (3_statement_cross) │
     │     └── rerate_narrative (mdna)            │
     └────────────────────────────────────────────┘
                           │
     ┌─────── Phase 4 (Eval Loop) ─────┐
     │ hard_rule → schema → LLM eval   │
     │ FAIL → retry with hint (max 2)  │
     └─────────────────────────────────┘
                           │
     ┌─────── Prior Year (同 Phase 1+2) ┐
     └──────────────────────────────────┘
                           │
     ┌─────── Synthesis ───────────────┐
     │ cross_year_compare              │
     │ insight_synthesis               │
     └─────────────────────────────────┘
                           │
     ┌─────── Phase 5 ────────────────┐
     │ completeness_check (Grade A-D) │
     └────────────────────────────────┘
                           │
                     report_writer.py
                     ├── report.md
                     ├── report.pdf
                     └── raw.json
```

## Agent / Skill 清單

| Agent | Skill | Input | 說明 |
|-------|-------|-------|------|
| business | business_analysis | Item 1 | 公司定位、成長敘事、業務結構、競爭優勢 |
| competitor_mapping | competitor_mapping | Item 1 | 對手清單、市場定位、揭露品質（Q1 用去年 10-K baseline） |
| supply_chain | supply_chain_analysis | Item 1+1A+7+8 footnotes | 原物料、單一來源風險、地緣 / 集中 / 短缺分類、跨期改善/惡化訊號 |
| risk | risk_analysis | Item 1A | 風險清單、跨年變動、措辭強度 |
| mdna | mdna_analysis | Item 7 | 業績驅動因子、管理層語氣、承諾追蹤 |
| governance | governance_analysis | Item 9A+10+11+13 | 審計意見、薪酬結構、治理品質 |
| fn_revenue | footnotes_revenue | Note A+B | 收入認列政策、會計準則變動 |
| fn_segment | footnotes_segment | Note C+D | 部門結構、重組活動 |
| fn_receivables | footnotes_receivables | Note L+Q | 應收帳款證券化、債務結構 |
| fn_assets | footnotes_assets | Note M+N+O+R | 存貨、商譽、金融工具 |
| fn_risk | footnotes_risk | Note U+V+P | 或有負債、承諾、租賃 |
| fn_pension | footnotes_pension | Note G | 退休金資金缺口、精算假設 |
| fn_compensation | footnotes_compensation | Note I+J+K | 股權薪酬、EPS、AOCI |
| fn_tax | footnotes_tax | Note H | 所得稅、遞延稅、不確定稅務部位 |
| terms_glossary | terms_glossary | 全文摘要 | 術語表（附錄） |
| financial | financial_analysis | XBRL+FS+fn | 財務指標趨勢、交叉驗證 |
| segment_trend | segment_trend | XBRL+biz+mdna | 部門營收佔比趨勢、結構轉型識別 |
| 3_stmt_cross | three_statement_cross | financial+XBRL | 三表矛盾檢查、bullish/bearish 訊號 |
| rerate_structure | rerate_structure | segment_trend | 營收結構是否轉型（獨立判斷） |
| rerate_quality | rerate_quality | 3_stmt_cross | 營收品質是否改善（獨立判斷） |
| rerate_narrative | rerate_narrative | mdna | 敘事是否從計畫轉成果（獨立判斷） |
| unusual_ops | unusual_operations | fn+fin+原文 | 不尋常會計操作識別 |
| cross_year | cross_year_compare | 兩年結果 | 跨年度矛盾與印證 |
| insight | insight_synthesis | 全部結果 | Bull/Bear/追蹤指標 |
| completeness | completeness_check | 全部結果 | 六維度品質評分 |
| eval | eval_analysis | 各 agent 輸出 | LLM-as-Judge 品質評分 |

## 報告結構

### 第一部分：Earnings Call（前瞻、非 GAAP，來自管理層自述）
1. **Forward Guidance**（硬指引表格 + 軟指引列表 + 指引變化對比 + 隱含訊號）
2. **Market Concerns**（top 3-5 分析師高頻議題 + 管理層回應 + verbatim 引用 + 迴避訊號）
3. **Earnings Call Highlights**（structured_summary + sentiment + partnerships）

> *若該季 transcript 未能取得，三節改顯示 placeholder「無 earnings call 資料」。*

`─── 以下章節來自 10-Q / 10-K 申報文件 · 財務數字採用 GAAP 會計準則 ───`

### 第二部分：10-Q / 10-K 申報文件分析（歷史、GAAP）
4. **財務數據**（指標表格 + 季度趨勢折線圖 + 資本配置 + 趨勢摘要 + 品質警示 + 異常值）
5. 公司定位
6. Competitor Landscape（10-K / Q1，Q1 標註 baseline 來源）
7. 成長敘事 + 終端市場組合表
8. 供應鏈分析（10-K + Q1，6 子段：整體 / 原物料 / 主要風險 / 跨期變化 / MD&A 實際影響 / 採購承諾）
9. 整體信心
10. 多頭論點（Bull Case）
11. 空頭論點（Bear Case）
12. **評價趨勢判斷**（🟢🟡🔴 紅綠燈 + 論述）
13. 關鍵追蹤指標（未來兩季）
14. 10K 洞察（Information Edge）
15. 競爭壓力（即時訊號）（Q2/Q3 10-Q）
16. 跨年度分析
17. 不尋常操作
18. 交叉驗證
19. 附錄：關鍵術語

## 專案結構

```
tenk/
├── main.py                          # CLI 入口（--market sec / jp / tw-equity）
├── config.json                      # API key + model（.gitignore）
├── config.example.json              # 設定範本
├── requirements.txt
├── agents/
│   └── analyst_agent.md             # 共用 agent 定義
├── skills/                          # skill .md，依市場分子目錄（名稱全域唯一）
│   ├── common/                      # 市場無關：eval／synthesis／rerate／cross_year／三表交叉
│   ├── us/                          # SEC 10-K／10-Q 專用
│   ├── jp/                          # jp_* EDINET／TDNET 專用
│   └── tw/                          # tw_* 台股分析、tw_accounting_qa 問答
├── docs/jp/                         # JP 資料來源使用條款
├── runtime/
│   ├── agent_runner.py              # LLM 呼叫（依 config provider 切換）+ context log + dry-run
│   ├── mock_outputs.json            # dry-run 用的 mock skill 結果
│   ├── orchestrator.py              # 多階段執行 + eval loop + checkpoint
│   ├── pipeline_state.py            # per-agent checkpoint/resume
│   ├── eval_runner.py               # hard rule + schema + LLM eval
│   ├── report_writer.py             # 繁中 MD + PDF + 折線圖
│   ├── report.css                   # PDF 樣式
│   ├── fonts/                       # PDF 中文字型
│   │
│   ├── sec_data_fetcher.py          # [US] EDGAR HTM + XBRL
│   ├── doc_converter.py             # [US] iXBRL strip + BeautifulSoup / markitdown fallback
│   ├── section_splitter.py          # [US] TOC-guided + LLM fallback + footnotes 切割
│   │
│   ├── jp_data_fetcher.py           # [JP] EDINET API + DuckDB index + ticker map
│   ├── jp_ixbrl_parser.py           # [JP] iXBRL 5 年表 + narrative chapter splitter
│   ├── jp_tdnet_scraper.py          # [JP] TDNET HTML scraper + PDF parse (markitdown)
│   ├── jp_pipeline.py               # [JP] orchestrator（yuho / event / watch 三 mode）
│   ├── jp_report_writer.py          # [JP] 報告（重用 SEC PDF css helper）
│   │
│   ├── transcript_scraper/          # 法說會逐字稿（US Yahoo Finance、JP logmi）
│   │   ├── scraper.py / parser.py / models.py          # US transcript
│   │   ├── logmi_scraper.py / logmi_parser.py          # JP logmi
│   │   └── node/                    # Stagehand LOCAL 模式 sidecar（src/scrape.ts、src/scrape-logmi.ts）
│   │
│   └── tw_equity/                   # [TW] --market tw-equity
│       ├── tw_pipeline.py           # orchestrator（單年度＋跨年）
│       ├── inputs.py                # tw_equity_inputs/<ticker>.json 載入與驗證
│       ├── pdf_doc.py               # pdfplumber／PyMuPDF 封裝＋快取
│       ├── ocr.py / ocr_adapters.py # OCR：Mistral 為主、Azure DI 備援
│       ├── doc_anchor.py / sections.py / tables.py   # 章節錨定、段落組裝、表格解析
│       ├── statements.py            # 合併財報三表逐列解析、科目對照、帳本與勾稽
│       ├── fh_schema.py / fh_notes.py               # 金控／銀行三表 schema 與附註
│       ├── fy_income.py             # 全年損益表與 TTM
│       ├── metrics.py               # 帳本衍生指標與 bridge 變動歸因
│       ├── cross_year.py            # 跨年比對（無 LLM）
│       ├── ar_sections.py           # 年報三章節（現金流量、重要契約、特別記載事項）
│       ├── tasks.py / report.py     # skill task 清單；md＋pdf＋raw.json 輸出
│       ├── qa.py / qa_llm.py        # 會計問答（模板／LLM＋數字核對）
│       ├── batch.py / batch_summary.py              # 批次 runner、跨公司排名與紅旗
│       └── *_acceptance.py          # 驗收工具（fs／fh／fy／ar）
│
├── tests/                           # pytest（tests/tw_equity、tests/fixtures）
├── tw_equity_inputs/                # 台股輸入檔（只附範例 2330、3653）
├── tw_report/                       # 台股年報／財報 PDF（.gitignore）
└── data/                            # （.gitignore）
    ├── cache/
    │   ├── pipeline_{ticker}_{year}.json    # SEC checkpoint
    │   ├── jp/
    │   │   ├── master.duckdb        # ticker_map + filings_index + tdnet_index
    │   │   ├── _scanned_dates.json  # EDINET scan checkpoint
    │   │   ├── _tdnet_scanned_dates.json
    │   │   ├── raw/{edinet_code}/   # EDINET ZIP
    │   │   ├── extracted/{doc_id}/  # ZIP 解壓
    │   │   └── tdnet/{YYYYMMDD}/    # TDNET PDF
    │   └── tw_equity/               # PDF 解析與 OCR 快取（.json／.ocr.json）
    └── output/
        ├── {TICKER}/                # 按公司分（HWM, 6315, 2330, ...）
        ├── batch/{YYYYMMDD-HHMMSS}/ # tw-equity 批次輸出
        └── contexts/                # API call log（共用）
```
